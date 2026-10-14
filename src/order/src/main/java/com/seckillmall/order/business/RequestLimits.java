package com.seckillmall.order.business;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
@Component
public class RequestLimits extends OncePerRequestFilter {
  @Override
  protected void doFilterInternal(HttpServletRequest r, HttpServletResponse response,
      FilterChain chain) throws ServletException, IOException {
    if (!r.getRequestURI().startsWith("/api/")) {
      chain.doFilter(r, response);
      return;
    }
    if (r.getQueryString() != null
        && (hasNonCanonicalParameterName(r.getQueryString())
            || Arrays.stream(r.getParameterMap().values().toArray(String[][] ::new))
                   .anyMatch(v -> v.length != 1))) {
      reject(response, 400, "INVALID_ARGUMENT");
      return;
    }
    byte[] body = r.getInputStream().readNBytes(16385);
    if (body.length > 16384) {
      reject(response, 413, "PAYLOAD_TOO_LARGE");
      return;
    }
    chain.doFilter(new HttpServletRequestWrapper(r) {
      @Override
      public ServletInputStream getInputStream() {
        ByteArrayInputStream input = new ByteArrayInputStream(body);
        return new ServletInputStream() {
          public int read() {
            return input.read();
          }
          public boolean isFinished() {
            return input.available() == 0;
          }
          public boolean isReady() {
            return true;
          }
          public void setReadListener(ReadListener l) {
            throw new UnsupportedOperationException();
          }
        };
      }
      @Override
      public BufferedReader getReader() {
        return new BufferedReader(new InputStreamReader(getInputStream(), StandardCharsets.UTF_8));
      }
    }, response);
  }
  private static boolean hasNonCanonicalParameterName(String query) {
    if (query.isEmpty()) return false;
    return Arrays.stream(query.split("&", -1)).map(pair -> {
      int separator = pair.indexOf('=');
      return separator < 0 ? pair : pair.substring(0, separator);
    }).anyMatch(key -> !key.matches("[A-Za-z][A-Za-z0-9_-]*"));
  }
  private static void reject(HttpServletResponse response, int status, String code)
      throws IOException {
    response.setStatus(status);
    response.setContentType("application/json");
    response.getWriter().write("{\"code\":\"" + code + "\",\"retryable\":false}");
  }
}
