data "aws_ecr_authorization_token" "token" {}

resource "aws_ecr_repository" "weather" {
  name                 = var.resources_name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = false
  }

  # This is used when initially creating the repository, to push an empty dummy image
  # to it. This is because when we provision the Lambda, it fails to reference an
  # empty repository.
  provisioner "local-exec" {
    command = <<EOF
      docker login ${data.aws_ecr_authorization_token.token.proxy_endpoint} -u AWS -p ${data.aws_ecr_authorization_token.token.password}
      docker pull alpine
      docker tag alpine ${self.repository_url}:latest
      docker push ${self.repository_url}:latest
      EOF
  }
}

