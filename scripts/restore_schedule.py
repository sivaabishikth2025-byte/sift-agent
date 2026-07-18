"""Restore the daily 06:00 America/New_York schedule after an autonomy test."""
import boto3

NAME = "sift-agent-SiftSchedule-47ZRWU6ZMJF9"
FN = "arn:aws:lambda:us-east-1:120569623789:function:sift-agent-SiftFunction-KjssVCcHzLDV"
ROLE = "arn:aws:iam::120569623789:role/sift-agent-SchedulerInvokeRole-t6pXIUVO0dY9"

c = boto3.client("scheduler", region_name="us-east-1")
c.update_schedule(
    Name=NAME,
    ScheduleExpression="cron(0 6 * * ? *)",
    ScheduleExpressionTimezone="America/New_York",
    FlexibleTimeWindow={"Mode": "OFF"},
    State="ENABLED",
    Target={"Arn": FN, "RoleArn": ROLE, "Input": '{"trigger": "schedule"}'},
)
print("Schedule restored to cron(0 6 * * ? *) America/New_York.")
