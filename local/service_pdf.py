"""Documento interno; acceso autenticado mediante la ruta de órdenes."""
from receipt_pdf import render_receipt

def render_service(order):
    return render_receipt(dict(order,_service=True))
