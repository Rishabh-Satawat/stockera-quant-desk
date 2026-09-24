import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY", "YOUR_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET", "YOUR_API_SECRET")

captured_request_token = None
server_instance = None


class CallbackHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    global captured_request_token
    parsed_path = urllib.parse.urlparse(self.path)
    query_params = urllib.parse.parse_qs(parsed_path.query)

    if "request_token" in query_params:
      captured_request_token = query_params["request_token"][0]

      # Send a clean success response back to the browser
      self.send_response(200)
      self.send_header("Content-type", "text/html; charset=utf-8")
      self.end_headers()
      html_response = """
            <!DOCTYPE html>
            <html>
            <head><title>Authentication Successful</title></head>
            <body style="font-family: system-ui; text-align: center; padding-top: 50px; background: #0f172a; color: white;">
                <h1 style="color: #22c55e;">&#10004; Authentication Successful!</h1>
                <p style="font-size: 18px; color: #94a3b8;">Zerodha session token captured. You can close this tab now.</p>
            </body>
            </html>
            """
      self.wfile.write(html_response.encode("utf-8"))
    else:
      self.send_response(400)
      self.end_headers()
      self.wfile.write(b"No request_token found in callback.")

  def log_message(self, format, *args):
    # Suppress default server logs for a clean terminal output
    return


def start_listener(port=5000):
  global server_instance
  server_instance = HTTPServer(("127.0.0.1", port), CallbackHandler)
  server_instance.serve_forever()


def main():
  print("=" * 60)
  print("🚀 Zerodha Kite Connect — Pro Token Generator")
  print("=" * 60)

  if not API_KEY or API_KEY == "YOUR_API_KEY":
    print("❌ Error: Please set your KITE_API_KEY in .env or the script.")
    sys.exit(1)

  # Start the background HTTP listener on port 5000
  server_thread = threading.Thread(target=start_listener, daemon=True)
  server_thread.start()
  print("🟢 Local callback listener started on http://127.0.0.1:5000/login")

  # Open the official Kite login URL in the browser
  login_url = f"https://kite.zerodha.com/connect/login?api_key={API_KEY}&v=3"
  print(f"\n🌐 Opening browser for Zerodha authentication...")
  webbrowser.open(login_url)
  print(f"👉 If the browser doesn't open automatically, visit:\n   {login_url}\n")
  print("⏳ Waiting for login confirmation...")

  # Wait until the token is captured
  timeout = 90
  start_time = time.time()
  while captured_request_token is None:
    if time.time() - start_time > timeout:
      print("\n❌ Timeout: No login callback received within 90 seconds.")
      sys.exit(1)
    time.sleep(0.5)

  print(
      f"✅ Captured request_token:"
      f" {captured_request_token[:8]}...{captured_request_token[-4:]}"
  )

  # Exchange request_token for access_token
  try:
    kite = KiteConnect(api_key=API_KEY)
    data = kite.generate_session(
        captured_request_token, api_secret=API_SECRET
    )
    access_token = data["access_token"]
    user_name = data.get("user_name", "Trader")

    # Persist the token
    with open("access_token.txt", "w") as f:
      f.write(access_token)

    with open(".env", "w") as f:
      f.write(f"""KITE_API_KEY={API_KEY}
KITE_API_SECRET={API_SECRET}
KITE_ACCESS_TOKEN={access_token}
""")

    print("-" * 60)
    print(f"🎉 Login Successful for {user_name}!")
    print(f"🔑 Access Token: {access_token[:8]}...{access_token[-4:]}")
    print("📁 Saved to: access_token.txt & .env")
    print("-" * 60)

  except Exception as e:
    print(f"❌ Error exchanging token: {e}")
    sys.exit(1)


if __name__ == "__main__":
  main()