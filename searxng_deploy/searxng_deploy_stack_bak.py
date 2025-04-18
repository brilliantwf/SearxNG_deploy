import os
import typing
from urllib.parse import urlparse
from aws_cdk import (
    Duration,
    Stack,
    aws_ecr,
    aws_lambda,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    CfnOutput,
    Fn
)
from constructs import Construct

class SearxNGFunctionStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)


        image_name    = "searxng"

        ##
        ## If use_pre_existing_image is True
        ## then use an image that already exists in ECR.
        ## Otherwise, build a new image
        ##
        use_pre_existing_image = False



        ##
        ## ECR  
        ##
        if (use_pre_existing_image):

            ##
            ## Container was build previously, or elsewhere.
            ## Use the pre-existing container
            ##
            ecr_repository = aws_ecr.Repository.from_repository_attributes(self,
                id              = "ECR",
                repository_arn  ='arn:aws:ecr:{0}:{1}:repository'.format(Aws.REGION, Aws.ACCOUNT_ID),
                repository_name = image_name
            ) ## aws_ecr.Repository.from_repository_attributes
            print (Aws.REGION, Aws.ACCOUNT_ID)
            ecr_image = typing.cast("aws_lambda.Code", aws_lambda.EcrImageCode(
                repository = ecr_repository
            )) ## aws_lambda.EcrImageCode

        else:
            ##
            ## Create new Container Image.
            ##
            ecr_image = aws_lambda.EcrImageCode.from_asset_image(
                directory = os.path.join(os.getcwd(), "docker")
            )

        ## Lambda Function
        ##
        myfunc = aws_lambda.Function(self,
          id            = "lambdaContainerFunction",
          description   = "Lambda Container Function",
          code          = ecr_image,
          ##
          ## Handler and Runtime must be *FROM_IMAGE*
          ## when provisioning Lambda from Container.
          ##
          handler       = aws_lambda.Handler.FROM_IMAGE,
          runtime       = aws_lambda.Runtime.FROM_IMAGE,
          #environment   = {"AWS_LWA_INVOKE_MODE":"RESPONSE_STREAM"},
          function_name = "searxng-function",
          memory_size   = 128,
          reserved_concurrent_executions = 10,
          timeout       = Duration.seconds(120)
        ) 
        # attach policy
        myfunc_role = myfunc.role
        myfunc_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))
        # myfunc_role.attach_inline_policy(iam.Policy(self, "MyInlinePolicy",
        #     statements=[
        #         iam.PolicyStatement(
        #             effect=iam.Effect.ALLOW,
        #             actions=["bedrock:InvokeModelWithResponseStream"],
        #             resources=["*"]
        #         )
        #     ]
        # ))

        aws_lambda.CfnPermission(self, "MyCfnPermission1",
            action="lambda:InvokeFunctionUrl",
            function_name=myfunc.function_name,
            principal="edgelambda.amazonaws.com",
            function_url_auth_type="AWS_IAM"
        )
        aws_lambda.CfnPermission(self, "MyCfnPermission2",
            action="lambda:InvokeFunctionUrl",
            function_name=myfunc.function_name,
            principal="cloudfront.amazonaws.com",
            function_url_auth_type="AWS_IAM"
        )

        ## aws_lambda.Function
        self.my_function_url = myfunc.add_function_url(
            auth_type = aws_lambda.FunctionUrlAuthType.AWS_IAM,
            invoke_mode = aws_lambda.InvokeMode.BUFFERED
        )
        CfnOutput(self, "searxng-function-url", value=self.my_function_url.url)


class EdgelambdaStack(Stack):
    def __init__(self, scope: Construct, id: str,searxng_function_stack:SearxNGFunctionStack, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)
        domain_name = Fn.select(2, Fn.split("/", searxng_function_stack.my_function_url.url))
        edge_lambda_role = iam.Role(self, "edge_lambda_role",assumed_by=iam.CompositePrincipal(iam.ServicePrincipal("edgelambda.amazonaws.com"),iam.ServicePrincipal("lambda.amazonaws.com")))

        edge_lambda_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaRole"))
        ## signv4 lambda deployment
        edgelambda = aws_lambda.Function(self, "edgelambda",
            code=aws_lambda.Code.from_asset("cloudfront_function/edge_lambda"),
            handler="mini_lambda_handler.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            environment={
                "main_url": self.node.try_get_context('main_url')
            },
            role=edge_lambda_role,
            timeout=Duration.seconds(10)
        )
        edge_lambda_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))
        edge_lambda_role.attach_inline_policy(iam.Policy(self, "invokelambdaurl",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["lambda:InvokeFunctionUrl"],
                    resources=["*"]
                )
            ]
        ))
        ## cloudfront distribution
        searxng_distribution = cloudfront.Distribution(self, "searxng-distribution",
            default_behavior=cloudfront.BehaviorOptions(
                compress=True,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                origin=origins.HttpOrigin(domain_name,custom_headers={"TARGET_ORIGIN":domain_name}),
                edge_lambdas=[cloudfront.EdgeLambda(
                    function_version=edgelambda.current_version,
                    event_type=cloudfront.LambdaEdgeEventType.ORIGIN_REQUEST,
                    include_body=True
                )]
            )
        ) 

        CfnOutput(self, "searxng-distribution-url", value="https://"+searxng_distribution.domain_name)
