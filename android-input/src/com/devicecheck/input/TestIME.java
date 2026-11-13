package com.devicecheck.input;
import android.inputmethodservice.InputMethodService;
import android.content.*;
import android.os.Build;
import android.util.Base64;
import android.view.inputmethod.InputConnection;
import java.nio.charset.StandardCharsets;
public class TestIME extends InputMethodService {
 private final BroadcastReceiver receiver=new BroadcastReceiver(){
  public void onReceive(Context c, Intent i){
   InputConnection ic=getCurrentInputConnection();
   if(ic==null){setResultCode(2);return;}
   boolean ok=false;
   if("com.devicecheck.input.CLEAR".equals(i.getAction())){
    ic.beginBatchEdit();ok=ic.deleteSurroundingText(100000,100000);ic.endBatchEdit();
   }else if("com.devicecheck.input.TEXT".equals(i.getAction())){
    try {String v=new String(Base64.decode(i.getStringExtra("msg"),Base64.DEFAULT),StandardCharsets.UTF_8);ok=ic.commitText(v,1);}catch(Exception e){ok=false;}
   }
   setResultCode(ok?1:2);
  }
 };
 public void onCreate(){super.onCreate();IntentFilter f=new IntentFilter();f.addAction("com.devicecheck.input.CLEAR");f.addAction("com.devicecheck.input.TEXT");if(Build.VERSION.SDK_INT>=33)registerReceiver(receiver,f,"android.permission.DUMP",null,Context.RECEIVER_EXPORTED);else registerReceiver(receiver,f,"android.permission.DUMP",null);}
 public void onDestroy(){unregisterReceiver(receiver);super.onDestroy();}
}
