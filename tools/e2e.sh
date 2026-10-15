#!/bin/bash
# Автотест макроса на настоящем Android: подставная игра + макрос ловят рыбу несколько минут.
set -u
APP=app.sakura.fishing
FAKE=app.fakefish
DURATION=${DURATION:-240}
OUT=e2e-out
mkdir -p $OUT
adb wait-for-device
adb shell input keyevent 82 >/dev/null 2>&1
adb install -r -g app/build/outputs/apk/debug/app-debug.apk || { echo "::error::install app failed"; exit 1; }
adb install -r -g fakefish/build/outputs/apk/debug/fakefish-debug.apk || { echo "::error::install fake failed"; exit 1; }
adb shell settings put system accelerometer_rotation 0
adb shell settings put system user_rotation 1
cat > $OUT/config.json <<'J'
{"platform":"android","cast":{"x":0.80,"y":0.33},"collect":{"x":0.40,"y":0.47},"rod":{"x":0.93,"y":0.90},
 "collect_mode":"click","rod_key":"slot","reequip":true,"migr2":true,"migr4":true,"game_pkg":"fakefish",
 "scan_area":{"x":0.728,"y":0.15,"w":0.046,"h":0.56}}
J
adb shell "run-as $APP mkdir -p files"
adb shell "run-as $APP sh -c 'cat > files/config.json'" < $OUT/config.json
adb shell "run-as $APP sh -c 'touch files/e2e.flag; rm -f files/e2e.log'"
adb shell am start -n $FAKE/.MainActivity
sleep 4
adb logcat -c
adb shell settings put secure enabled_accessibility_services $APP/app.sakura.fishing.MacroAccess
adb shell settings put secure accessibility_enabled 1
sleep 6
adb shell appops set $APP PROJECT_MEDIA allow >/dev/null 2>&1
adb shell am start -n $APP/.MainActivity --ez e2e true
for i in $(seq 1 25); do
  sleep 2
  adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1
  adb pull /sdcard/ui.xml $OUT/ui.xml >/dev/null 2>&1
  if xy=$(python3 tools/ui_tap.py $OUT/ui.xml "start now,начать,android:id/button1"); then
    echo "tap $xy"; adb shell input tap $xy; break
  fi
done
sleep 5
adb shell am start -n $FAKE/.MainActivity
echo "== играем $DURATION с =="
for i in $(seq 1 $((DURATION/20))); do
  sleep 20
  adb logcat -d -s FAKEFISH:I | grep STAT | tail -1
done
adb logcat -d -s FAKEFISH:I > $OUT/fake.log
adb shell "run-as $APP cat files/e2e.log" > $OUT/app.log 2>&1
adb shell "run-as $APP cat files/anime-fishing-error.log" > $OUT/crash.log 2>&1
adb logcat -d -s SakuraFishing:V AndroidRuntime:E python.stderr:V python.stdout:V > $OUT/sys.log 2>&1
adb exec-out screencap -p > $OUT/final.png
python3 tools/e2e_report.py $OUT/fake.log $OUT/app.log
rc=$?
if [ -s $OUT/crash.log ] && ! grep -q "No such file" $OUT/crash.log; then
  echo "::warning title=crash log::$(tail -c 3000 $OUT/crash.log | sed ':a;N;$!ba;s/%/%25/g;s/\n/%0A/g')"
fi
if [ $rc -ne 0 ]; then
  echo "::warning title=sys.log::$(tail -c 3500 $OUT/sys.log | sed ':a;N;$!ba;s/%/%25/g;s/\n/%0A/g')"
fi
exit $rc
