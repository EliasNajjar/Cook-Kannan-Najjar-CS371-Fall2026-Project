## Contact Info

Group Members & Email Addresses:

Mohandass Kannan, mka377@uky.edu\
Elias Najjar, esna222@uky.edu

## Versioning

Github Link: https://github.com/EliasNajjar/Kannan-Najjar-CS371-Fall2026-Project

## General Info
This file describes how to install/run your program and anything else you think the user should know

## Install Instructions

Run the following line to install the required libraries for this project:

`pip3 install -r requirements.txt`

## Running the game

From the project directory, start the server:

```sh
python pong/pongServer.py
```

Start a client on each player's computer (or two clients locally):

```sh
python pong/pongClient.py
```

Enter the server computer's IP address and port `65432`. For local testing, use
`127.0.0.1`. Use the up and down arrow keys to move your paddle. The server
listens on all interfaces; remote connections require TCP port 65432 to be
reachable through the host's firewall.

The match starts when two players connect. First to five points wins. A third
client receives a game-full message. If a player leaves, the match resets and
the remaining player waits for a replacement. Close the game window to leave.

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

TCP messages use newline-delimited JSON. The initial `hello` contains `width`,
`height`, and `side`. Each `paddle` message contains `y`; its `state` response
contains both paddle positions, ball position, scores, winner, readiness, tick,
and cumulative point/bounce counters for sound playback. A buffered reader and
`sendall` handle fragmented and combined TCP messages. Connections time out after
five seconds without a completed network operation.

## Verification

```sh
python -m unittest discover -s tests -v
```