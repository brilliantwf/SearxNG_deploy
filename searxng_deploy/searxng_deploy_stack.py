import os
from aws_cdk import (
    Duration,
    Stack,
    Environment,
    aws_lambda,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct

class SearxNGFunctionStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # 从 context 读取 main_url
        self.main_url = self.node.try_get_context('main_url')
        
        # 获取当前区域
        current_region = Stack.of(self).region
        

        # 构建并推送镜像到 ECR
        ecr_image = aws_lambda.EcrImageCode.from_asset_image(
            directory=os.path.join(os.getcwd(), "app_docker")
        )

        # 创建 Lambda 函数
        myfunc = aws_lambda.Function(
            self, "lambdaContainerFunction",
            description="Lambda Container Function",
            code=ecr_image,
            handler=aws_lambda.Handler.FROM_IMAGE,
            runtime=aws_lambda.Runtime.FROM_IMAGE,
            function_name=f"searxng-function-{current_region}",
            memory_size=128,
            reserved_concurrent_executions=10,
            timeout=Duration.seconds(120)
        )

        # 添加权限
        myfunc_role = myfunc.role
        myfunc_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )

        # 添加 Lambda 权限
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

        # 添加函数 URL
        function_url = myfunc.add_function_url(
            auth_type=aws_lambda.FunctionUrlAuthType.AWS_IAM,
            invoke_mode=aws_lambda.InvokeMode.BUFFERED
        )
        
        # 输出函数 URL
        CfnOutput(self, "searxng-function-url", value=function_url.url)
        
        # 暴露函数 URL 供其他 stack 使用
        self.function_url = function_url.url

class SearxngEdgelambdaStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, searxng_function_stack: SearxNGFunctionStack, **kwargs) -> None:
        # 获取 edgelambda_region
        edgelambda_region = scope.node.try_get_context('edgelambda_region')
        if not edgelambda_region:
            raise ValueError("No edgelambda_region specified in cdk.context.json")
            
        # 设置环境并启用跨区域引用
        kwargs['env'] = Environment(region=edgelambda_region)
        kwargs['cross_region_references'] = True
        
        super().__init__(scope, construct_id, **kwargs)
        
        self._region = edgelambda_region
        
        edge_lambda_role = iam.Role(self, "edge_lambda_role",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("edgelambda.amazonaws.com"),
                iam.ServicePrincipal("lambda.amazonaws.com")
            )
        )

        edge_lambda_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaRole"))
        ## signv4 lambda deployment
        edgelambda = aws_lambda.Function(self, "edgelambda",
            code=aws_lambda.Code.from_asset("cloudfront_function/edge_lambda"),
            handler="auth_lambda_handler.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
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
        custom_origin = self.node.try_get_context('custom_origin')
        if not custom_origin:
            raise ValueError("No custom_origin specified in cdk.context.json")
        ## cloudfront distribution
        searxng_distribution = cloudfront.Distribution(self, "searxng-distribution",
            default_behavior=cloudfront.BehaviorOptions(
                compress=True,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                origin=origins.HttpOrigin(domain_name=custom_origin,custom_headers={"TARGET_ORIGIN":self.node.try_get_context('custom_origin')}),
                edge_lambdas=[cloudfront.EdgeLambda(
                    function_version=edgelambda.current_version,
                    event_type=cloudfront.LambdaEdgeEventType.ORIGIN_REQUEST,
                    include_body=True
                )]
            )
        ) 

        CfnOutput(self, "searxng-distribution-url", value="https://"+searxng_distribution.domain_name)

