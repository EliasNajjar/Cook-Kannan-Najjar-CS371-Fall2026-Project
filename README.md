## Contact Info

Group Members & Email Addresses:

Mohandass Kannan, mka377@uky.edu\
Elias Najjar, esna222@uky.edu\
Hayden Cook, hwco227@uky.edu

## Versioning

Github Link: https://github.com/EliasNajjar/Kannan-Najjar-CS371-Fall2026-Project

## Install Instructions

Use Python 3.10 or later with Tkinter installed. From the project directory, install the dependency:

```sh
python -m pip install -r requirements.txt
```

## Running the game

From the project directory, start the server:

```sh
python -B pong/pongServer.py --leaderboard-port 8080
```

Start a client on each player's computer (or two clients locally):

```sh
python -B pong/pongClient.py
```

Enter the server's IP address, game port `65432`, a username, and one to three
initials. For local testing, use `127.0.0.1` and a different username in each
client. Use the up and down arrow keys to move your paddle. The server listens
on all interfaces by default. For LAN play, make TCP port `65432` reachable
through the server computer's firewall.

The server pairs players as they join and can run multiple matches at once.
First to five points wins. Both players must click **Play Again** for a rematch.
Close the game window to leave. The remaining player returns to matchmaking.

With the example command, open `http://127.0.0.1:8080/leaderboard` on the server
computer to see the leaderboard. For LAN access, use the server's IP address
and make TCP port `8080` reachable. The leaderboard resets when the server
restarts. The default HTTP port is `80` when `--leaderboard-port` is omitted.
Use `--port` to change the game port and enter that port in each client.

## Client and server responsibilities

The client reads keyboard input, moves only its own paddle, and sends its paddle's
vertical position. A background network thread receives snapshots without
blocking the display. The client uses those snapshots to draw the other paddle,
ball, score, and winner, and to play point and bounce sounds.

The server assigns left/right player slots, clamps incoming paddle positions to
the court, and runs ball movement, paddle/wall collisions, scoring, and win
detection at 60 ticks per second. Both clients receive state from this single
simulation. Paddle positions are client-controlled; movement-speed validation is
not implemented.

TCP messages use newline-delimited JSON. The client sends a `join` with a
username and initials, and the server replies with a `hello` containing the
court dimensions. The client then sends `update` messages with its paddle
position, the match and round identifiers, and its rematch choice. The server
replies with a `state` snapshot for that player. Connections time out after five
seconds without a completed network operation.

## Verification

To verify a local setup, start the server and two clients. Move each paddle and
confirm both windows show the same ball and scores. Play to five points, check
the winner's leaderboard entry, and click **Play Again** in both windows to
confirm the scores reset. Close one window and confirm the other returns to
matchmaking.
