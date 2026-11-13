import os,subprocess,shutil
from pathlib import Path
root=Path(__file__).resolve().parent
out=root.parent/'.runtime/devicecheck-input';out.mkdir(parents=True,exist_ok=True)
sdk=Path.home()/'Library/Android/sdk';tools=sdk/'build-tools/34.0.0';jar=sdk/'platforms/android-34/android.jar'
env=dict(os.environ);env['JAVA_HOME']=subprocess.check_output(['/usr/libexec/java_home'],text=True).strip()
def run(args):subprocess.run([str(a) for a in args],check=True,env=env,stdout=subprocess.DEVNULL)
classes=out/'classes';classes.mkdir(exist_ok=True)
run([Path(env['JAVA_HOME'])/'bin/javac','-source','8','-target','8','-classpath',jar,'-d',classes,*root.glob('src/**/*.java')])
run([tools/'d8','--lib',jar,'--output',out,*classes.glob('**/*.class')])
run([tools/'aapt','package','-f','-M',root/'AndroidManifest.xml','-S',root/'res','-I',jar,'-F',out/'unsigned.apk'])
import zipfile
with zipfile.ZipFile(out/'unsigned.apk','a') as z:z.write(out/'classes.dex','classes.dex')
run([tools/'zipalign','-f','4',out/'unsigned.apk',out/'aligned.apk'])
key=out/'debug.keystore'
if not key.exists():run([Path(env['JAVA_HOME'])/'bin/keytool','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','devicecheck','-dname','CN=DeviceCheck Test','-keyalg','RSA','-validity','3650'])
run([tools/'apksigner','sign','--ks',key,'--ks-pass','pass:android','--out',out/'input.apk',out/'aligned.apk'])
print(out/'input.apk')
