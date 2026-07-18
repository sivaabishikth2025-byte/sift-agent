import boto3

try:
    c = boto3.client("bedrock-runtime", region_name="us-east-1")
    r = c.converse(
        modelId="amazon.nova-lite-v1:0",
        messages=[{"role": "user", "content": [{"text": "Reply with the single word: ready"}]}],
        inferenceConfig={"maxTokens": 10, "temperature": 0},
    )
    print("NOVA OK ->", r["output"]["message"]["content"][0]["text"].strip())
except Exception as e:
    print("NOVA ERROR ->", type(e).__name__, str(e)[:400])
