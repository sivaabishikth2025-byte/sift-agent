"""Temporarily set the EventBridge schedule to fire once, ~N minutes from now,
so we can prove the agent runs itself (no manual invoke). Prints the exact UTC
time it will fire. Run restore_schedule.py afterwards to put it back to daily.
"""
import sys
from datetime import datetime, timedelta, timezone
import boto3

NAME = "sift-agent-SiftSchedule-47ZRWU6ZMJF9"
FN = "arn:aws:lambda:us-east-1:120569623789:function:sift-agent-SiftFunction-KjssVCcHzLDV"
ROLE = "arn:aws:iam::120569623789:role/sift-agent-SchedulerInvokeRole-t6pXIUVO0dY9"

mins = int(sys.argv[1]) if len(sys.argv) > 1 else 3
fire = (datetime.now(timezone.utc) + timedelta(minutes=mins)).replace(microsecond=0)
expr = f"at({fire.strftime('%Y-%m-%dT%H:%M:%S')})"

c = boto3.client("scheduler", region_name="us-east-1")
c.update_schedule(
    Name=NAME,
    ScheduleExpression=expr,
    ScheduleExpressionTimezone="UTC",
    FlexibleTimeWindow={"Mode": "OFF"},
    State="ENABLED",
    Target={"Arn": FN, "RoleArn": ROLE, "Input": '{"trigger": "schedule"}'},
)
print(f"Schedule set to fire ONCE at {expr} UTC (in ~{mins} min). No manual invoke.")
