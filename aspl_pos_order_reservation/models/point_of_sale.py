# -*- coding: utf-8 -*-
#################################################################################
# Author      : Acespritech Solutions Pvt. Ltd. (<www.acespritech.com>)
# Copyright(c): 2012-Present Acespritech Solutions Pvt. Ltd.
# All Rights Reserved.
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#################################################################################

import logging
from openerp import tools, models, fields, api, _
from datetime import datetime, timedelta
from openerp.exceptions import Warning, UserError
import time
from pytz import timezone
from openerp.tools import float_is_zero
import psycopg2
_logger = logging.getLogger(__name__)

class pos_order(models.Model):
    _inherit = "pos.order"

    @api.one
    def update_delivery_date(self, delivery_date):
        res = self.write({ 'delivery_date': datetime.strptime(delivery_date, '%Y-%m-%d') })
        if res:
            return self.read()[0]
        return False

    @api.multi
    def write(self, vals):
        res = super(pos_order, self).write(vals)
        if self._context.get('out_order'):
            return res
        for each in self:
            if vals.get('state') == 'paid' and each.reserved:
                picking_id = each.picking_id.copy()
                picking_type_id = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', each.picking_id.picking_type_id.warehouse_id.id), ('code', '=', 'outgoing')], limit=1)
                if picking_type_id:
                    location_dest_id, supplierloc = self.env['stock.warehouse']._get_partner_locations()
                    name = self.env['stock.picking.type'].browse(vals.get('picking_type_id', picking_type_id.id)).sequence_id.next_by_id()
                    picking_id.write({'picking_type_id':picking_type_id.id,'location_id':each.picking_id.location_dest_id.id,
                                      'location_dest_id': location_dest_id.id,'name':name, 'origin':each.name})
                    if picking_id.pack_operation_pack_ids:
                        picking_id.pack_operation_pack_ids.write({'location_id':each.picking_id.location_dest_id.id,
                                      'location_dest_id': location_dest_id.id})
                    if picking_id.move_lines:
                        picking_id.move_lines.write({'location_id':each.picking_id.location_dest_id.id,
                                      'location_dest_id': location_dest_id.id, 'origin':each.name})
                    picking_id.action_confirm()
                    picking_id.force_assign()
                    picking_id.button_validate()
                    stock_transfer_id = self.env['stock.immediate.transfer'].search([('pick_ids', '=', picking_id.id)], limit=1).process()
                    if stock_transfer_id:
                        stock_transfer_id.process()
                    query = ''' UPDATE pos_order SET unreserved=True,
                       picking_id='%s'
                       WHERE id=%s''' % (picking_id.id,each.id)
                    self._cr.execute(query)
                    each.write({'picking_id' :picking_id.id})
        return res

    @api.multi
    def action_pos_order_paid(self):
        if not self.test_paid():
            raise UserError(_("Order is not paid."))
        self.write({'state': 'paid'})
        #custom code
        picking_id_cust = False
        location_dest_id, supplierloc = self.env['stock.warehouse']._get_partner_locations()
        if self.order_status in ['full','partial'] or self.order_booked:
            for line in self.lines:
                if line.product_id.type != 'service' and not line.cancel_item and line.line_status == 'nothing':
                    #customer delivery order
                    picking_type_out = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', self.picking_id.picking_type_id.warehouse_id.id), ('code', '=', 'outgoing')], limit=1)
                    if picking_type_out:
                        picking_vals_rev = {
                                'name' : picking_type_out.sequence_id.next_by_id(),
                                'picking_type_id': picking_type_out.id,
                                'location_id': self.config_id.reserve_stock_location_id.id,
                                'location_dest_id': location_dest_id.id,
                                'state': 'draft',
                                'origin':self.name
                            }
                        if not picking_id_cust:
                            picking_id_cust = self.env['stock.picking'].create(picking_vals_rev)
                        self.env['stock.move'].create({
                                        'product_id': line.product_id.id,
                                        'name': line.product_id.name,
                                        'product_uom_qty': line.qty,
                                        'location_id': self.config_id.reserve_stock_location_id.id,
                                        'location_dest_id': location_dest_id.id,
                                        'product_uom': line.product_id.uom_id.id,
                                        'origin' : self.name,
                                        'picking_id' : picking_id_cust.id
                                    })
            if picking_id_cust and picking_id_cust.move_lines:
                picking_id_cust.action_confirm()
                picking_id_cust.force_assign()
                picking_id_cust.button_validate()
                stock_transfer_id = self.env['stock.immediate.transfer'].search([('pick_ids', '=', picking_id_cust.id)], limit=1).process()
                if stock_transfer_id:
                    stock_transfer_id.process()
                self.with_context({'out_order' :True}).write({'picking_id' : picking_id_cust.id,'unreserved':True})
            elif picking_id_cust:
                picking_id_cust.unlink()
        return self.create_picking()

    def _order_fields(self, ui_order):
        res = super(pos_order, self)._order_fields(ui_order)
        res.update({
            'order_booked' : ui_order.get('reserved') or False,
            'reserved': ui_order.get('reserved') or False,
            'delivery_date': ui_order.get('delivery_date') or False,
            'cancel_order': ui_order.get('cancel_order_ref') or False,
            'customer_email': ui_order.get('customer_email') or False,
            'fresh_order': ui_order.get('fresh_order') or False,
            'partial_pay': ui_order.get('partial_pay') or False,
        })
        return res

    def create_picking(self):
        if self.order_status not in ['full','partial'] and not self.order_booked:
            super(pos_order, self).create_picking()
        return True

    @api.model
    def _process_order(self, order):
        #initialization
        pos_line_obj = self.env['pos.order.line']
        move_obj = self.env['stock.move']
        picking_obj = self.env['stock.picking']
        stock_imm_tra_obj = self.env['stock.immediate.transfer']
        draft_order_id = order.get('old_order_id')
        picking_type_id = False
        picking_id_cust = False
        picking_id_rev = False
        if order.get('draft_order'):
            if not draft_order_id:
                order.pop('draft_order')
                order_id = self.create(self._order_fields(order))
                return order_id
            else:
                order_id = draft_order_id
                pos_line_ids = pos_line_obj.search([('order_id', '=', order_id)])
                if pos_line_ids:
                    pos_line_obj.unlink(pos_line_ids)
                self.write([order_id],
                           {'lines': order['lines'],
                            'partner_id': order.get('partner_id')})
                return order_id

        if not order.get('draft_order') and draft_order_id:
            order_id = draft_order_id
            order_obj = self.browse(order_id)
            pos_line_ids = pos_line_obj.search([('order_id', '=', order_id)])
            if pos_line_ids:
                if not order.get('cancel_order'):
                    for line_id in pos_line_ids:
                        line_id.unlink()
            temp = order.copy()
            temp.pop('statement_ids', None)
            temp.pop('name', None)
            temp.update({
                'date_order': order.get('creation_date')
            })
            warehouse_id = self.env['stock.warehouse'].search([
                    ('lot_stock_id', '=', order_obj.config_id.stock_location_id.id)], limit=1)
            location_dest_id, supplierloc = self.env['stock.warehouse']._get_partner_locations()
            if warehouse_id:
                picking_type_id = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', warehouse_id.id), ('code', '=', 'internal')])
            for line in order.get('lines'):
                prod_id = self.env['product.product'].browse(line[2].get('product_id'))
                prod_dict = line[2]
                if prod_id.type != 'service' and prod_dict and prod_dict.get('cancel_item'):
                    #customer delivery order
                    picking_type_out = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', order_obj.picking_id.picking_type_id.warehouse_id.id), ('code', '=', 'outgoing')], limit=1)
                    if picking_type_out:
                        picking_id_cust = picking_obj.create({
                                'name' : picking_type_out.sequence_id.next_by_id(),
                                'picking_type_id': picking_type_out.id,
                                'location_id': order_obj.config_id.reserve_stock_location_id.id,
                                'location_dest_id': location_dest_id.id,
                                'state': 'draft',
                                'origin':order_obj.name
                            })
                    if order_obj.picking_id:
                        # unreserve order
                        picking_id_rev = picking_obj.create({
                                'name' : picking_type_out.sequence_id.next_by_id(),
                                'picking_type_id': order_obj.picking_id.picking_type_id.id,
                                'location_id': order_obj.config_id.reserve_stock_location_id.id,
                                'location_dest_id': order_obj.config_id.stock_location_id.id,
                                'state': 'draft',
                                'origin':order_obj.name
                            })
                        if prod_dict.get('consider_qty') and not order_obj.order_status == 'partial' and not order.get('reserved'):
                            move_obj.create({
                                    'product_id': prod_id.id,
                                    'name': prod_id.name,
                                    'product_uom_qty': prod_dict.get('consider_qty'),
                                    'location_id': order_obj.config_id.reserve_stock_location_id.id,
                                    'location_dest_id': location_dest_id.id,
                                    'product_uom': prod_id.uom_id.id,
                                    'origin' : order_obj.name,
                                    'picking_id' : picking_id_cust.id
                                })
                        if prod_dict.get('cancel_qty'):
                            move_obj.create({
                                    'product_id': prod_id.id,
                                    'name': prod_id.name,
                                    'product_uom_qty': abs(prod_dict.get('cancel_qty')),
                                    'location_id': order_obj.config_id.reserve_stock_location_id.id,
                                    'location_dest_id': order_obj.config_id.stock_location_id.id,
                                    'product_uom': prod_id.uom_id.id,
                                    'origin' : order_obj.name,
                                    'picking_id' : picking_id_rev.id
                                })
            if picking_id_cust and picking_id_cust.move_lines:
                picking_id_cust.action_confirm()
                picking_id_cust.force_assign()
                picking_id_cust.button_validate()
                stock_transfer_id = stock_imm_tra_obj.search([('pick_ids', '=', picking_id_cust.id)], limit=1).process()
                if stock_transfer_id:
                    stock_transfer_id.process()
                order_obj.with_context({'out_order' :True}).write({'picking_id' : picking_id_cust.id,'unreserved':True})
            elif picking_id_cust:
                picking_id_cust.unlink()
            if picking_id_rev and picking_id_rev.move_lines:
                picking_id_rev.action_confirm()
                picking_id_rev.force_assign()
                picking_id_rev.button_validate()
                stock_transfer_id = stock_imm_tra_obj.search([('pick_ids', '=', picking_id_rev.id)], limit=1).process()
                if stock_transfer_id:
                    stock_transfer_id.process()
                order_obj.with_context({'out_order' :True}).write({'picking_id' : picking_id_rev.id,'unreserved':True})
            elif picking_id_rev:
                picking_id_rev.unlink()
            order_obj.write(temp)
            for payments in order['statement_ids']:
                order_obj.with_context({'from_pos':True}).add_payment(self._payment_fields(payments[2]))

            session = self.env['pos.session'].browse(order['pos_session_id'])
            if session.sequence_number <= order['sequence_number']:
                session.write({'sequence_number': order['sequence_number'] + 1})
                session.refresh()

            if not float_is_zero(order['amount_return'], self.env['decimal.precision'].precision_get('Account')) or order['cancel_order']:
                cash_journal = session.cash_journal_id
                if not cash_journal:
                    cash_journal_ids = session.statement_ids.filtered(lambda st: st.journal_id.type == 'cash')
                    if not len(cash_journal_ids):
                        raise Warning(_('error!'),
                                             _("No cash statement found for this session. Unable to record returned cash."))
                    cash_journal = cash_journal_ids[0].journal_id
                order_obj.with_context({'from_pos':True}).add_payment({
                    'amount': -order['amount_return'],
                    'payment_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'payment_name': _('return'),
                    'journal': cash_journal.id,
                })
            return order_obj
        if not order.get('draft_order') and not draft_order_id:
            order_id = super(pos_order, self)._process_order(order)
            if order_id.reserved:
                order_id.do_internal_transfer()
            return order_id

    @api.multi
    def do_internal_transfer(self):
        for order in self:
            if order.config_id.reserve_stock_location_id and order.config_id.stock_location_id:
                # Move Lines
                temp_move_lines = []
                for line in order.lines:
                    if line.product_id.default_code:
                        name = [line.product_id.default_code]
                    else:
                        name = line.product_id.name
                    if line.product_id.type != "service":
                        move_vals = (0,0,{
                            'product_id': line.product_id.id,
                            'name': name,
                            'product_uom_qty': line.qty,
                            'location_id': order.config_id.stock_location_id.id,
                            'location_dest_id': order.config_id.reserve_stock_location_id.id,
                            'product_uom': line.product_id.uom_id.id,
                        })
                        temp_move_lines.append(move_vals)
                warehouse_obj = self.env['stock.warehouse'].search([
                    ('lot_stock_id', '=', order.config_id.stock_location_id.id)], limit=1)
                if warehouse_obj:
                    picking_type_obj = self.env['stock.picking.type'].search([
                        ('warehouse_id', '=', warehouse_obj.id), ('code', '=', 'internal')])
                    if picking_type_obj and temp_move_lines:
                        
                        picking_vals = {
                            'picking_type_id': picking_type_obj.id,
                            'location_id': order.config_id.stock_location_id.id,
                            'location_dest_id': order.config_id.reserve_stock_location_id.id,
                            'state': 'draft',
                            'move_lines': temp_move_lines,
                            'origin':order.name
                        }
                        picking_obj = self.env['stock.picking'].create(picking_vals)
                        if picking_obj:
                            picking_obj.action_confirm()
                            picking_obj.force_assign()
                            picking_obj.button_validate()
                            stock_transfer_id = self.env['stock.immediate.transfer'].search([('pick_ids', '=', picking_obj.id)], limit=1)
                            if stock_transfer_id:
                                stock_transfer_id.process()
                            order.picking_id = picking_obj.id

    @api.multi
    @api.depends('amount_total', 'amount_paid')
    def _compute_amount_due(self):
        for each in self:
            each.amount_due = each.amount_total - each.amount_paid

    @api.multi
    @api.depends('lines')
    def _find_order_status(self):
        for order in self:
            partial, full = [], []
            line_count = 0;
            line_partial = False
            for line in order.lines:
                if not line.cancel_item:
                    line_count += 1
                    if line.line_status == "partial":
                        order.order_status = "partial"
                        line_partial = True
                        break
                    if line.line_status == "full":
                        full.append(True)
            if len(full) == line_count:
                if not False in full and not line_partial:
                    order.order_status = "full"
            elif full:
                order.order_status = "partial"

    reserved = fields.Boolean("Reserved", readonly=True)
    partial_pay = fields.Boolean("Partial Pay", readonly=True)
    order_booked = fields.Boolean("Booked", readonly=True)
    unreserved = fields.Boolean("Unreserved")
    amount_due = fields.Float(string='Amount Due', compute='_compute_amount_due')
    delivery_date = fields.Date(string="Delivery Date")
    cancel_order = fields.Char('Cancel Order')
    order_status = fields.Selection([('full', 'Fully Cancelled'), ('partial', 'Partially Cancelled')],
                                    'Order Status', compute="_find_order_status")
    customer_email = fields.Char('Customer Email')
    fresh_order = fields.Boolean("Fresh Order")

    @api.model
    def add_payment(self, data):
        """Create a new payment for the order"""
        if data['amount'] == 0.0:
            return
        return super(pos_order, self).add_payment(data)

    @api.one
    def send_reserve_mail(self):
        if self and self.customer_email and self.reserved and self.fresh_order:
            try:
                template_id = self.env['ir.model.data'].get_object_reference('aspl_pos_order_reservation', 'email_template_pos_ereceipt')
                template_obj = self.env['mail.template'].browse(template_id[1])
                template_obj.send_mail(self.id,force_send=True, raise_exception=True)
            except Exception as e:
                _logger.error('Unable to send email for order %s', e)

    @api.model
    def ac_pos_search_read(self, domain):
        domain = domain.get('domain')
        search_vals = self.search_read(domain)
        user_id = self.env['res.users'].browse(self._uid)
        tz = False
        if self._context and self._context.get('tz'):
            tz = timezone(self._context.get('tz'))
        elif user_id and user_id.tz:
            tz = timezone(user_id.tz)
        if tz:
            c_time = datetime.now(tz)
            hour_tz = int(str(c_time)[-5:][:2])
            min_tz = int(str(c_time)[-5:][3:])
            sign = str(c_time)[-6][:1]
            result = []
            for val in search_vals:
                if sign == '-':
                    val.update({
                        'date_order':(datetime.strptime(val.get('date_order'), '%Y-%m-%d %H:%M:%S') - timedelta(hours=hour_tz, minutes=min_tz)).strftime('%Y-%m-%d %H:%M:%S')
                    })
                elif sign == '+':
                    val.update({
                        'date_order':(datetime.strptime(val.get('date_order'), '%Y-%m-%d %H:%M:%S') + timedelta(hours=hour_tz, minutes=min_tz)).strftime('%Y-%m-%d %H:%M:%S')
                    })
                result.append(val)
        else:
            result = search_vals
        for res in result:
            line_dict = self.env['pos.order.line'].browse(res.get('lines'))
            if line_dict:
                res['lines'] = line_dict.read()
        return result
    @api.model
    def create_from_ui(self, orders):
        # Keep only new orders
        submitted_references = [o['data']['name'] for o in orders]
        pos_order = self.search([('pos_reference', 'in', submitted_references)])
        existing_orders = pos_order.read(['pos_reference'])
        existing_references = set([o['pos_reference'] for o in existing_orders])
        orders_to_save = [o for o in orders if o['data']['name'] not in existing_references]
        order_ids = []

        for tmp_order in orders_to_save:
            to_invoice = tmp_order['to_invoice']
            order = tmp_order['data']
            if to_invoice:
                self._match_payment_to_invoice(order)
            pos_order = self._process_order(order)
            if pos_order :
                to_be_cancelled_items = {}
                for line in order.get('lines'):
                    if line[2].get('cancel_process'):
                        if line[2].get('product_id') in to_be_cancelled_items:
                            to_be_cancelled_items[line[2].get('product_id')] = to_be_cancelled_items[line[2].get('product_id')] + line[2].get('qty')
                        else:
                            to_be_cancelled_items.update({line[2].get('product_id'):line[2].get('qty')})
                for line in order.get('lines'):
                    for item_id in to_be_cancelled_items:
                        cancel_lines = []
                        if line[2].get('cancel_process'):
                            cancel_lines = self.browse([line[2].get('cancel_process')[0]]).lines
                        for origin_line in cancel_lines:
                            if to_be_cancelled_items[item_id] == 0:
                                continue
                            if origin_line.qty > 0 and item_id == origin_line.product_id.id:
                                if (to_be_cancelled_items[item_id] * -1) >= origin_line.qty:
                                    ret_from_line_qty = 0
                                    to_be_cancelled_items[item_id] = to_be_cancelled_items[item_id] + origin_line.qty
                                else:
                                    ret_from_line_qty = to_be_cancelled_items[item_id] + origin_line.qty
                                    to_be_cancelled_items[item_id] = 0
                                origin_line.write({'qty': ret_from_line_qty})
            order_ids.append(pos_order.id)

            try:
                if order and not order.get('set_as_draft'):
                    pos_order.action_pos_order_paid()
            except psycopg2.OperationalError:
                # do not hide transactional errors, the order(s) won't be saved!
                raise
            except Exception as e:
                _logger.error('Could not fully process the POS Order: %s', tools.ustr(e))

            if to_invoice:
                pos_order.action_pos_order_invoice()
                pos_order.invoice_id.sudo().action_invoice_open()
                pos_order.account_move = pos_order.invoice_id.move_id
        return order_ids


class PosConfig(models.Model):
    _inherit = 'pos.config'

    enable_order_reservation = fields.Boolean('Enable Order Reservation')
    reserve_stock_location_id = fields.Many2one('stock.location','Reserve Stock Location')
    cancellation_charges_type = fields.Selection([('fixed','Fixed'),('percentage', 'Percentage')], 'Cancellation Charges Type')
    cancellation_charges = fields.Float('Cancellation Charges')
    cancellation_charges_product_id = fields.Many2one('product.product','Cancellation Charges Product')
    last_days = fields.Char("Last Days")
    record_per_page = fields.Integer("Record Per Page")
    prod_for_payment = fields.Many2one('product.product',string='Paid Amount Product',
                                      help="This is a dummy product used when a customer pays partially. This is a workaround to the fact that Odoo needs to have at least one product on the order to validate the transaction.")
    refund_amount_product_id = fields.Many2one('product.product','Refund Amount Product')
    enable_pos_welcome_mail = fields.Boolean("Send Welcome Mail")
    allow_reservation_with_no_amount = fields.Boolean("Allow Reservation With 0 Amount")


class pos_order_line(models.Model):
    _inherit = 'pos.order.line'

    @api.model
    def create(self, values):
        if values.get('product_id'):
            if self.env['pos.order'].browse(values['order_id']).session_id.config_id.prod_for_payment.id == values.get('product_id'):
                return
            if self.env['pos.order'].browse(values['order_id']).session_id.config_id.refund_amount_product_id.id == values.get('product_id'):
                return
        res = super(pos_order_line, self).create(values)
        if values.get('cancel_item_id'):
            line_id = self.browse(values.get('cancel_item_id'))
            if values.get('new_line_status'):
                line_id.write({'line_status': values.get('new_line_status')})
        return res

    cancel_item = fields.Boolean("Cancel Item")
    line_status = fields.Selection([('nothing', 'Nothing'), ('full', 'Fully Cancelled'), ('partial', 'Partially Cancelled')],
                                    'Order Status', default="nothing")

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _confirm_orders(self):
        for session in self:
            company_id = session.config_id.journal_id.company_id.id
            orders = session.order_ids.filtered(lambda order: order.state == 'paid')
            journal_id = self.env['ir.config_parameter'].sudo().get_param(
                'pos.closing.journal_id_%s' % company_id, default=session.config_id.journal_id.id)

            move = self.env['pos.order'].with_context(force_company=company_id)._create_account_move(session.start_at, session.name, int(journal_id), company_id)
            orders.with_context(force_company=company_id)._create_account_move_line(session, move)
            for order in session.order_ids.filtered(lambda o: o.state not in ['done', 'invoiced']):
                if order.state not in ('draft'):
                    # raise UserError(_("You cannot confirm all orders of this session, because they have not the 'paid' status"))
                    order.action_pos_order_done()

    @api.multi
    def action_pos_session_open(self):
        pos_order = self.env['pos.order'].search([('state', '=', 'draft')])
        for order in pos_order:
            if order.session_id.state != 'opened':
                order.write({'session_id': self.id})
        return super(PosSession, self).action_pos_session_open()


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    @api.one
    @api.constrains('amount')
    def _check_amount(self):
        if not self._context.get('from_pos'):
            super(AccountBankStatementLine, self)._check_amount()

    @api.one
    @api.constrains('amount', 'amount_currency')
    def _check_amount_currency(self):
        if not self._context.get('from_pos'):
            super(AccountBankStatementLine, self)._check_amount_currency()


class res_partner(models.Model):
    _inherit="res.partner"

    @api.multi
    def _compute_remain_credit_limit(self):
        for partner in self:
            total_credited = 0
            orders = self.env['pos.order'].search([('partner_id', '=', partner.id),
                                                   ('state', '=', 'draft')])
            for order in orders:
                total_credited += order.amount_due
            partner.remaining_credit_limit = partner.credit_limit - total_credited

    remaining_credit_limit = fields.Float("Remaining Credit Limit", compute="_compute_remain_credit_limit")

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
