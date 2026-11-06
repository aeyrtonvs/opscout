# Alarms for example-api (fake values, spec 012 evals).
resource "aws_cloudwatch_metric_alarm" "example_api_5xx" {
  alarm_name          = "example-api-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  dimensions = {
    LoadBalancer = "app/example-api-alb/0123456789abcdef"
  }
}
