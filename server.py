import socket
import json
import threading
import random
import pygame
from game import Game, Player
from powerup import Powerup


clients = []
clients_lock = threading.Lock()
shutdown_event = threading.Event()

def is_valid_spawn(game_map, x, y):
    """Checks if the given coordinates are a valid spawn position (black cell)."""
    if 0 <= y < len(game_map) and 0 <= x < len(game_map[0]):
        return game_map[y][x] == 0
    return True

def handle_client(conn, client_id, client_player):
    buffer = ""
    try:
        while not shutdown_event.is_set():  # Check for shutdown signal
            data = conn.recv(1024).decode()
            if not data:
                break
            buffer += data
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                try:
                    msg = json.loads(line)
                    if msg["type"] == "pos":
                        pos = msg["data"]
                        client_player.x = pos["x"]
                        client_player.y = pos["y"]
                except Exception as e:
                    print(f"Error processing message from client {client_id}: {e}")
    except Exception as e:
        print(f"Client {client_id} connection error: {e}")
    finally:
        print(f"Client {client_id} disconnected")
        conn.close()
        with clients_lock:
            for i, (cid, _, _) in enumerate(clients):
                if cid == client_id:
                    clients.pop(i)
                    break

def broadcast_state(game, server_player, powerups):
    with clients_lock:
        state = {
            "type": "state",
            "data": {
                "server": {
                    "id": "server",
                    "x": server_player.x,
                    "y": server_player.y,
                    "role": server_player.role
                },
                "clients": {
                    str(cid): {
                        "id": str(cid),
                        "x": pl.x - 0.4,
                        "y": pl.y - 0.4,
                        "role": pl.role,
                        "ghost": pl.ghost,
                        "shield": pl.shield
                    } for cid, pl, _ in clients
                },
                "powerups": powerups.powerup_positions
            }
        }
        msg = (json.dumps(state) + "\n").encode()
        for _, _, conn in clients:
            try:
                conn.sendall(msg)
            except Exception as e:
                print("Error sending state to a client:", e)




def check_tagging(game):
    tagger = None
    with clients_lock:
        for cid, pl, _ in clients:
            if pl.role == "tagger":
                tagger = pl
                break
    if tagger:
        # Check all clients.
        with clients_lock:
            for cid, pl, _ in clients:
                if pl.role == "runner" and abs(tagger.x - pl.x) < 0.5 and abs(tagger.y - pl.y) < 0.5:
                    if pl.shield:
                        return
                    else:
                        pl.role = "tagger"

def accept_clients(server_socket, game, used_spawns):
    """Continuously accepts new clients and assigns them a spawn."""
    client_id_counter = 1
    tagger_assigned = False  # Flag to ensure only one tagger

    while not shutdown_event.is_set():
        try:
            conn, addr = server_socket.accept()
            print(f"Client {client_id_counter} connected: {addr}")
            # Send the map so the client can initialize its game state.
            map_msg = json.dumps({"type": "map", "data": game.game_map}) + "\n"
            try:
                conn.sendall(map_msg.encode())
            except Exception as e:
                print("Error sending map:", e)
                conn.close()
                continue

            # Send the client ID
            id_msg = json.dumps({"type": "client_id", "data": client_id_counter}) + "\n"
            try:
                conn.sendall(id_msg.encode())
            except Exception as e:
                print("Error sending client ID:", e)
                conn.close()
                continue

            # Find a valid spawn position.
            while True:
                x = random.randint(0, len(game.game_map[0]) - 1)
                y = random.randint(0, len(game.game_map) - 1)
                if is_valid_spawn(game.game_map, x, y):
                    if client_id_counter == 2 and not tagger_assigned:  # Second client is tagger
                        client_player = Player(float(x), float(y), role="tagger")
                        tagger_assigned = True
                    else:
                        client_player = Player(float(x), float(y), role="runner")
                    break


            with clients_lock:
                clients.append((client_id_counter, client_player, conn))
            threading.Thread(target=handle_client, args=(conn, client_id_counter, client_player), daemon=True).start()
            client_id_counter += 1
        except socket.timeout:
            continue # Continue to check the shutdown_event
        except Exception as e:
            print(f"Error accepting client: {e}")
            break

def main():
    port = int(input("Enter port: "))
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('', port))
    server_socket.listen(5)  # Increase backlog if needed.
    server_socket.settimeout(1) # Add a timeout so the server doesnt get stuck
    print(f"Server listening on port {port}")

    game = Game()
    used_spawns = set()

    powerups = Powerup()
    powerups.spawn_powerups()

    # Start accepting clients in a separate thread.
    accept_thread = threading.Thread(target=accept_clients, args=(server_socket, game, used_spawns), daemon=True)
    accept_thread.start()

    server_player = game.local_player

    # Main game loop: process input, update the game, render and broadcast state.
    running = True
    try:
        while running:
            running = game.display_map()  # This handles movement, rendering, and events.
            server_player.x = 0.0
            server_player.y = 0.0
            server_player.role = game.local_player.role

            with clients_lock:
                for cid, pl in clients:
                    powerups.check_powerup_collisions(pl)

            broadcast_state(game, server_player, powerups)
            check_tagging(game)
    finally:
        shutdown_event.set()  # Signal shutdown to all threads
        print("Shutting down server...")

        # Close all client connections
        with clients_lock:
            for _, _, conn in clients:
                try:
                    conn.close()
                except Exception as e:
                    print("Error closing client connection:", e)

        server_socket.close()
        accept_thread.join() # Wait for the accept thread to finish
        pygame.quit()  # Cleanly exit pygame when done.
        print("Server shutdown complete.")

if __name__ == "__main__":
    main()
