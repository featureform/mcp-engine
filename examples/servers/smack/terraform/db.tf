data "aws_availability_zones" "available" {
  state = "available"
}

resource "random_password" "db" {
  length           = 16
  special          = true
  override_special = "_!%^"
}

resource "aws_db_instance" "db" {
  db_name              = "smack"
  allocated_storage    = 10
  engine               = "postgres"
  engine_version       = "17.2"
  instance_class       = "db.t4g.micro"
  skip_final_snapshot  = true
  publicly_accessible  = true
  db_subnet_group_name = aws_db_subnet_group.db.name
  vpc_security_group_ids = [aws_security_group.db.id]
  username             = "postgres"
  password             = random_password.db.result
}

resource "aws_security_group" "db" {
  name   = var.resources_name
  vpc_id = aws_vpc.db.id

  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc" "db" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
}

resource "aws_db_subnet_group" "db" {
  name       = "subnet"
  subnet_ids = aws_subnet.db[*].id
}

variable "public_subnet_cidrs" {
  type = list(string)
  description = "Public Subnet CIDR values"
  default = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

resource "aws_internet_gateway" "db" {
  vpc_id = aws_vpc.db.id
}

resource "aws_route_table" "db" {
  vpc_id = aws_vpc.db.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.db.id
  }
}

resource "aws_subnet" "db" {
  vpc_id            = aws_vpc.db.id
  count = length(var.public_subnet_cidrs)
  cidr_block        = var.public_subnet_cidrs[count.index]
  availability_zone = data.aws_availability_zones.available.names[count.index]
}

resource "aws_route_table_association" "db" {
  count = length(var.public_subnet_cidrs)
  subnet_id      = aws_subnet.db[count.index].id
  route_table_id = aws_route_table.db.id
}