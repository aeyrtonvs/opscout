# Networking only (fake values, spec 012 evals): no alarm is declared here.
resource "aws_vpc" "example" {
  cidr_block = "192.0.2.0/24"
}
