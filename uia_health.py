"""Bounded, read-only device probe independent of the Appium proxy."""
import subprocess
import time


def blocked(adb,device):
    for sample in range(2):
        try:
            result=subprocess.run([adb,'-s',device,'shell','ps','-A','-o','STAT,NAME'],capture_output=True,text=True,timeout=2)
        except (OSError,subprocess.TimeoutExpired):return False
        if result.returncode:return False
        rows=[line.split() for line in result.stdout.splitlines()]
        if not any(len(row)==2 and row[0].startswith('D') and row[1]=='io.appium.uiautomator2.server' for row in rows):return False
        if sample==0:time.sleep(.1)
    return True
