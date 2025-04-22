TODO: Update any region information in commands.

### Create an Elastic Container Repository

`aws ecr create-repository --repository-name mcp/weather`

`docker build --platform=linux/amd64 --provenance=false -t mcp/weather -f Dockerfile ../../..`

### Push image

TODO: Update instructions on how to get this
TODO: Make sure no account information left in commands
`aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 594284378315.dkr.ecr.us-east-2.amazonaws.com`

`docker tag mcp/weather:latest 594284378315.dkr.ecr.us-east-2.amazonaws.com/mcp/weather:latest`

`docker push 594284378315.dkr.ecr.us-east-2.amazonaws.com/mcp/weather:latest`

### Lambda

```shell
aws iam create-role \
    --role-name lambda-container-execution \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "lambda.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }'
    
aws iam attach-role-policy \
    --role-name lambda-container-execution \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

```shell
aws lambda create-function \
    --function-name weather \
    --package-type Image \
    --code ImageUri=${AWS_ACCOUNT_ID}.dkr.ecr.us-east-2.amazonaws.com/mcp/weather:latest \
    --role arn:aws:iam::${AWS_ACCOUNT_ID}:role/lambda-container-execution \
    --timeout 60 \
    --memory-size 512
```

```shell
aws lambda create-function-url-config \
    --function-name weather \
    --auth-type NONE
```

```shell
aws lambda add-permission \
    --function-name weather \
    --function-url-auth-type NONE \
    --action lambda:InvokeFunctionUrl \
    --statement-id PublicInvoke \
    --principal '*'
```

To update image used in lambda function:

```shell
aws lambda update-function-code \
    --function-name weather \
    --image-uri ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-2.amazonaws.com/mcp/weather:latest
```

### New way of tagging and pushing

// This is not used
`export REPOSITORY_URL=$(terraform output image_tag)`

`docker tag mcp/weather:latest $(terraform output -raw image_tag)`
`docker push $(terraform output -raw image_tag)`
`aws lambda update-function-code --function-name $(terraform output -raw lambda_name) --image-uri $(terraform output -raw image_tag)`