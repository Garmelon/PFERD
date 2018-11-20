import PFERD
import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.DEBUG, format=PFERD.LOG_FORMAT)
#logging.basicConfig(level=logging.INFO, format=PFERD.LOG_FORMAT)

async def test_download():
	auth = PFERD.ShibbolethAuthenticator(cookie_path="cookie_jar")
	soup = await auth.get_webpage("885157")
	await auth.close()
	if soup:
		print("Soup acquired!")
	else:
		print("No soup acquired :(")

def main():
	#print(f"  os.getcwd(): {os.getcwd()}")
	#print(f"  sys.argv[0]: {sys.argv[0]}")
	#print(f"         both: {os.path.dirname(os.getcwd() + '/' + sys.argv[0])}")
	#print(f"     __file__: {__file__}")
	#print(f"stackoverflow: {os.path.dirname(os.path.abspath(__file__))}")

	#asyncio.run(test_download(), debug=True)
	asyncio.run(test_download())

if __name__ == "__main__":
	main()
