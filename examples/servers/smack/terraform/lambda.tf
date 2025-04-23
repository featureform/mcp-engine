data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"

    principals {
      identifiers = ["lambda.amazonaws.com"]
      type = "Service"
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "lambda_role" {
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  name               = var.resources_name
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  role       = aws_iam_role.lambda_role.name
}

resource "aws_lambda_function" "weather_lambda" {
  function_name = var.resources_name
  role          = aws_iam_role.lambda_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.weather.repository_url}:latest"

  timeout     = 30
  memory_size = 512

  environment {
    variables = {
      DB_HOST     = aws_db_instance.db.address
      DB_NAME     = "smack"
      DB_USER     = "postgres"
      DB_PASSWORD = random_password.db.result
      DB_PORT     = aws_db_instance.db.port
    }
  }
}

resource "aws_lambda_function_url" "weather_lambda" {
  function_name      = aws_lambda_function.weather_lambda.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "allow_invoke_url" {
  statement_id           = "PublicInvokeFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.weather_lambda.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
