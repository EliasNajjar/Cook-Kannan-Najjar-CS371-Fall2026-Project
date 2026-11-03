# =================================================================================================
# Contributing Authors:	    <Anyone who touched the code>
# Email Addresses:          <Your uky.edu email addresses>
# Date:                     <The date the file was last edited>
# Purpose:                  <How this file contributes to the project>
# Misc:                     <Not Required.  Anything else you might want to include>
# =================================================================================================

import socket
import threading
from collections import deque

# Use this file to write your server logic
# You will need to support at least two clients
# You will need to keep track of where on the screen (x,y coordinates) each paddle is, the score 
# for each player and where the ball is, and relay that to each client
# I suggest you use the sync variable in pongClient.py to determine how out of sync your two
# clients are and take actions to resync the games

initInfo = "640 480 "

ip: str = "0.0.0.0"
port: int = 65432

clients = deque()

def handle_client(conn: socket.socket):
    conn.send((initInfo + ("left" if len(clients) == 1 else "right")).encode())
    while True:
        paddleMoving = conn.recv(1024).decode()
        for c in clients:
            if c != conn:
                c.send(paddleMoving.encode())

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

server.bind((ip, port))
server.listen()

server.settimeout(1.0)

while True:
    try:
        conn, addr = server.accept()
        clients.append(conn)
        threading.Thread(target=handle_client, args=(conn,)).start()
    except socket.timeout:
        continue