package com.seckillmall.order.business;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.*;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.ByteArrayInputStream;
import javax.imageio.ImageIO;
import com.google.zxing.*;
import com.google.zxing.common.HybridBinarizer;

/** 用临时RSA/AES测试密钥验证官方SDK；不连接微信、不使用商户私钥。 */
class WechatSecurityTest {
  @TempDir Path directory;
  KeyPair wechat;WechatSdk sdk;Map<String,String> env;
  final String aes="01234567890123456789012345678901";
  final ObjectMapper json=new ObjectMapper();
  void pem(Path file,String label,byte[] value)throws Exception{Files.writeString(file,"-----BEGIN "+label+"-----\n"+Base64.getMimeEncoder(64,new byte[]{10}).encodeToString(value)+"\n-----END "+label+"-----\n");}
  @BeforeEach void setup()throws Exception{
    var gen=KeyPairGenerator.getInstance("RSA");gen.initialize(2048);wechat=gen.generateKeyPair();var merchant=gen.generateKeyPair();
    pem(directory.resolve("private.pem"),"PRIVATE KEY",merchant.getPrivate().getEncoded());pem(directory.resolve("public.pem"),"PUBLIC KEY",wechat.getPublic().getEncoded());Files.writeString(directory.resolve("api-key"),aes);
    env=new HashMap<>(Map.of("WECHAT_MCH_ID","1900000001","WECHAT_APP_ID","wx1234567890123456","WECHAT_MERCHANT_SERIAL","0123456789ABCDEF","WECHAT_PRIVATE_KEY_PATH",directory.resolve("private.pem").toString(),"WECHAT_PAY_PUBLIC_KEY_PATH",directory.resolve("public.pem").toString(),"WECHAT_PAY_PUBLIC_KEY_ID","PUB_KEY_ID_TEST_2026","WECHAT_API_V3_KEY_PATH",directory.resolve("api-key").toString(),"WECHAT_NOTIFY_URL","https://example.com/api/payments/wechat/notify"));sdk=new WechatSdk(env);
  }
  Map<String,String> headers(String body,long timestamp)throws Exception{
    String nonce="headerNonce";var signature=Signature.getInstance("SHA256withRSA");signature.initSign(wechat.getPrivate());signature.update((timestamp+"\n"+nonce+"\n"+body+"\n").getBytes(StandardCharsets.UTF_8));
    return new HashMap<>(Map.of("Wechatpay-Serial",env.get("WECHAT_PAY_PUBLIC_KEY_ID"),"Wechatpay-Timestamp",Long.toString(timestamp),"Wechatpay-Nonce",nonce,"Wechatpay-Signature",Base64.getEncoder().encodeToString(signature.sign())));
  }
  String envelope(String event,Map<String,Object> payload)throws Exception{
    String nonce="unitnonce123",aad="transaction";var cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(aes.getBytes(StandardCharsets.UTF_8),"AES"),new GCMParameterSpec(128,nonce.getBytes(StandardCharsets.UTF_8)));cipher.updateAAD(aad.getBytes(StandardCharsets.UTF_8));
    return json.writeValueAsString(Map.of("id",UUID.randomUUID().toString(),"create_time",OffsetDateTime.now().toString(),"event_type",event,"resource_type","encrypt-resource","summary","支付通知","resource",Map.of("algorithm","AEAD_AES_256_GCM","nonce",nonce,"associated_data",aad,"ciphertext",Base64.getEncoder().encodeToString(cipher.doFinal(json.writeValueAsBytes(payload))))));
  }
  Map<String,Object> payment(){return Map.of("mchid",env.get("WECHAT_MCH_ID"),"appid",env.get("WECHAT_APP_ID"),"out_trade_no","a".repeat(32),"transaction_id","420000000000000000001","trade_state","SUCCESS","trade_type","NATIVE","amount",Map.of("total",200,"currency","CNY"));}
  @Test void sdkVerifiesAndDecryptsNotification()throws Exception{
    String body=envelope("TRANSACTION.SUCCESS",payment());var h=headers(body,Instant.now().getEpochSecond());var p=sdk.paymentNotification(h,body);
    assertEquals(200,p.total());assertEquals("SUCCESS",p.state());assertEquals(env.get("WECHAT_MCH_ID"),p.mchid());
    assertThrows(Fault.class,()->sdk.paymentNotification(h,body+" "));
    var wrong=new HashMap<>(h);wrong.put("Wechatpay-Serial","UNKNOWN");assertThrows(Fault.class,()->sdk.paymentNotification(wrong,body));
    var bad=new HashMap<>(h);bad.put("Wechatpay-Signature","WECHATPAY/SIGNTEST/INVALID");assertThrows(Fault.class,()->sdk.paymentNotification(bad,body));
    assertThrows(Fault.class,()->sdk.paymentNotification(headers(body,Instant.now().minusSeconds(600).getEpochSecond()),body));
  }
  @Test void refusesWrongEventAndCorruptedCiphertext()throws Exception{
    String body=envelope("TRANSACTION.OTHER",payment());assertThrows(Fault.class,()->sdk.paymentNotification(headers(body,Instant.now().getEpochSecond()),body));
    var tree=json.readTree(envelope("TRANSACTION.SUCCESS",payment()));((com.fasterxml.jackson.databind.node.ObjectNode)tree.get("resource")).put("ciphertext","AAAA");String broken=tree.toString();
    assertThrows(Fault.class,()->sdk.paymentNotification(headers(broken,Instant.now().getEpochSecond()),broken));
  }
  @Test void refundsAreVerifiedBySdk()throws Exception{
    String body=envelope("REFUND.SUCCESS",Map.of("out_trade_no","a".repeat(32),"transaction_id","420000000000000000001","out_refund_no","b".repeat(32),"refund_id","5030000000001","refund_status","SUCCESS","amount",Map.of("total",200,"refund",200,"currency","CNY")));
    var r=sdk.refundNotification(headers(body,Instant.now().getEpochSecond()),body);assertEquals("SUCCESS",r.state());assertEquals(200,r.amount());assertEquals(200,r.total());
  }
  @Test void localQrIsDecodableAndRejectsForeignUrl()throws Exception{
    String url="weixin://wxpay/bizpayurl?pr=unit_test_only";String image=WechatPayments.qr(url);var buffered=ImageIO.read(new ByteArrayInputStream(Base64.getDecoder().decode(image.substring(image.indexOf(',')+1))));
    int[] pixels=buffered.getRGB(0,0,280,280,null,0,280);var bitmap=new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(280,280,pixels)));
    assertEquals(url,new MultiFormatReader().decode(bitmap).getText());assertThrows(Fault.class,()->WechatPayments.qr("https://fake-payment.invalid"));
  }
  @Test void invalidConfigurationFailsClosed(){env.put("WECHAT_NOTIFY_URL","http://localhost/notify");assertThrows(IllegalArgumentException.class,()->new WechatSdk(env));}
}
