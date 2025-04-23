output "resources_name" {
  value = var.resources_name
}

output "repository_url" {
  value = aws_ecr_repository.weather.repository_url
}

output "image_tag" {
  value = "${aws_ecr_repository.weather.repository_url}:latest"
}

output "lambda_name" {
  value = aws_lambda_function.weather_lambda.function_name
}

output "lambda_url" {
  value = aws_lambda_function_url.weather_lambda.function_url
}

output "db_endpoint" {
  value = aws_db_instance.db.endpoint
}

output "db_password" {
  value     = random_password.db.result
  sensitive = true
}