variable "region" {
  description = "Name of the AWS region to provision the resources"
  type        = string
  default     = "us-east-1"
  nullable    = false
}

variable "resources_name" {
  description = "Name used for all of the resources that we will create"
  type        = string
  default     = "mcpengine-smack"
  nullable    = false
}
