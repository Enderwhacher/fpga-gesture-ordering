"""Reserve the same service port before touching OpenCV settings or the PL."""
from contextlib import contextmanager
import socket


@contextmanager
def exclusive_board_test(port=8765):
    # Binding all interfaces also excludes the normal ordering HTTP server.
    # Keep this reservation throughout the benchmark, including cleanup.
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            reservation.bind(('0.0.0.0', port))
            reservation.listen(1)
        except OSError as error:
            raise RuntimeError(f'Port {port} is occupied. Stop the board ordering service and its kernel before testing.') from error
        yield
    finally:
        reservation.close()
