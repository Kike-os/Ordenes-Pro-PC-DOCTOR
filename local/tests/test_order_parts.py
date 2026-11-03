"""Repuestos registrados desde la orden técnica (datos ficticios, base temporal): la salida «uso en orden» del inventario, una por producto y
orden, que consume la reserva de la orden, nunca deja existencias negativas, no se descuenta otra vez al facturar la orden y solo la registra
administración."""
import json
import unittest

import test_inventory_center as base
import app
import inventory_center


def helpers(cls):
    return {k: v for k, v in vars(cls).items() if not k.startswith('test_') and not k.startswith('__')}


class OrderPartsTests(unittest.TestCase):
    locals().update(helpers(base.InventoryCenterTests))

    def test_parts_used_from_the_order(self):
        self.admin()
        paste = self.new(self.category('Pasta térmica', 'Consumibles de servicio técnico'), 'Arctic', 'MX-4 ficticia', quantity=4)['body']['item']['id']
        made = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 ficticio', units=['S-1', 'S-2'])['body']
        ssd, units = made['item']['id'], [u['id'] for u in made['units']]
        order = self.order('partes-01')
        path = '/api/orders/%d/parts' % order['id']
        parts = self.get(path)['body']
        names = {p['id']: p for p in parts['available']}
        self.assertEqual((parts['used'], parts['reserved'], names[paste]['available'], len(names[ssd]['units'])), ([], [], 4, 2))
        # Repuesto a granel: sale de las existencias y queda en la orden.
        used = self.post(path, item_id=str(paste), quantity='1', request_key='repuesto-orden-000001')
        self.assertEqual(used['status'], 200, used['body'])
        self.assertEqual([(u['item_id'], u['quantity']) for u in used['body']['used']], [(paste, 1)])
        self.assertNotIn(paste, {p['id'] for p in used['body']['available']})  # una salida por producto y orden
        again = self.post(path, item_id=str(paste), quantity='1', request_key='repuesto-orden-000002')
        self.assertEqual(again['status'], 409)  # no se descuenta dos veces
        # Repuesto con serie reservado para la orden: la salida consume la reserva con la unidad elegida.
        reserve = self.post('/api/inventory/reservations', action='reserve', item_id=str(ssd), order_code=order['code'], unit_ids=json.dumps([units[1]]))
        self.assertEqual(reserve['status'], 200, reserve['body'])
        parts = self.get(path)['body']
        held = next(p for p in parts['available'] if p['id'] == ssd)
        self.assertEqual((len(parts['reserved']), held['reservation']['quantity']), (1, 1))
        done = self.post(path, item_id=str(ssd), unit_ids=json.dumps([units[1]]), reservation_id=str(held['reservation']['id']), request_key='repuesto-orden-000003')
        self.assertEqual(done['status'], 200, done['body'])
        self.assertEqual(([u['serials'] for u in done['body']['used'] if u['item_id'] == ssd], done['body']['reserved']), ([['S-2']], []))
        with app.connect() as c:
            stock = {p['id']: p['stock'] for p in inventory_center.products(c)}
        self.assertEqual((stock[paste], stock[ssd]), (3, 1))
        # Nunca existencias negativas.
        other = self.order('partes-02')
        too_many = self.post('/api/orders/%d/parts' % other['id'], item_id=str(paste), quantity='9', request_key='repuesto-orden-000004')
        self.assertIn(too_many['status'], (400, 409))
        with app.connect() as c:
            self.assertEqual({p['id']: p['stock'] for p in inventory_center.products(c)}[paste], 3)
            # La factura de la orden omite lo que ya salió por la orden.
            self.assertEqual(c.execute("SELECT COUNT(*) FROM inventory_movements WHERE reference_kind='orden' AND reference_id=?", (order['id'],)).fetchone()[0], 2)
        # Un técnico no registra ni ve los repuestos; una orden inexistente responde 404.
        tcookie, tcsrf = __import__('test_cash').CashTests.technician(self)
        self.assertEqual(self.request(path, cookie=tcookie)['status'], 403)
        self.assertEqual(self.request(path, {'item_id': str(paste), 'quantity': '1'}, cookie=tcookie, csrf=tcsrf)['status'], 403)
        self.assertEqual(self.get('/api/orders/999999/parts')['status'], 404)


if __name__ == '__main__':
    unittest.main()
