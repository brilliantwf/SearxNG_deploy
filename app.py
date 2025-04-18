from aws_cdk import App
from searxng_deploy.searxng_deploy_stack import SearxNGFunctionStack
from searxng_deploy.searxng_deploy_stack import SearxngEdgelambdaStack 
from searxng_deploy.route53_stack import Route53Stack

app = App()

# 从 CDK context 获取部署配置
searxng_regions = app.node.try_get_context('searxng_regions') or ["us-west-2"]
edgelambda_region = app.node.try_get_context('edgelambda_region') or "us-east-1"
# 存储所有创建的 SearxNG stacks，用于后续引用
searxng_stacks = {}

# 在多个区域部署 SearxNGFunctionStack
for region in searxng_regions:
    env = {'region': region}
    stack_name = f"SearxNGFunctionStack-{region}"
    stack = SearxNGFunctionStack(
        app, 
        stack_name, 
        env=env,
        cross_region_references=True
    )
    searxng_stacks[region] = stack

# 在指定区域部署 EdgelambdaStack
edgelambda_env = {'region': edgelambda_region}
searxng_edgelambda_stack = SearxngEdgelambdaStack(
    app, 
    "SearxngEdgelambdaStack", 
    searxng_function_stack=searxng_stacks[edgelambda_region],  # 使用相同区域的 SearxNG stack
    env=edgelambda_env,
    cross_region_references=True
)
# 部署 Route53 Stack
route53_stack = Route53Stack(
    app,
    "Route53Stack",
    searxng_stacks=searxng_stacks,
    env={'region': edgelambda_region},  # Route53 是全局服务，但我们需要指定一个区域
    cross_region_references=True
)

app.synth()

