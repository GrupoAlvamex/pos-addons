odoo.define('aspl_pos_order_reservation.models', function (require) {
	var models = require('point_of_sale.models');
	var rpc = require('web.rpc');
	var utils = require('web.utils');
	var round_pr = utils.round_precision;

    models.load_fields("res.partner", ['remaining_credit_limit', 'credit_limit']);

	var _super_Order = models.Order.prototype;
    models.Order = models.Order.extend({
        initialize: function(attributes,options){
            var self = this;
            var order_super = _super_Order.initialize.apply(this, arguments);
            this.set({
                'reservation_mode': false,
                'delivery_date': false,
                'draft_order': false,
                'paying_due': false,
                'fresh_order': false,
            })
            $('.js_reservation_mode').removeClass('highlight');
            return order_super;
        },
        generate_unique_id: function() {
            var timestamp = new Date().getTime();
            return Number(timestamp.toString().slice(-10));
        },
        // Order History
        set_sequence:function(sequence){
        	this.set('sequence',sequence);
        },
        get_sequence:function(){
        	return this.get('sequence');
        },
        set_order_id: function(order_id){
            this.set('order_id', order_id);
        },
        get_order_id: function(){
            return this.get('order_id');
        },
        set_amount_paid: function(amount_paid) {
            this.set('amount_paid', amount_paid);
        },
        get_amount_paid: function() {
            return this.get('amount_paid');
        },
        set_amount_return: function(amount_return) {
            this.set('amount_return', amount_return);
        },
        get_amount_return: function() {
            return this.get('amount_return');
        },
        set_amount_tax: function(amount_tax) {
            this.set('amount_tax', amount_tax);
        },
        get_amount_tax: function() {
            return this.get('amount_tax');
        },
        set_amount_total: function(amount_total) {
            this.set('amount_total', amount_total);
        },
        get_amount_total: function() {
            return this.get('amount_total');
        },
        set_company_id: function(company_id) {
            this.set('company_id', company_id);
        },
        get_company_id: function() {
            return this.get('company_id');
        },
        set_date_order: function(date_order) {
            this.set('date_order', date_order);
        },
        get_date_order: function() {
            return this.get('date_order');
        },
        set_pos_reference: function(pos_reference) {
            this.set('pos_reference', pos_reference)
        },
        get_pos_reference: function() {
            return this.get('pos_reference')
        },
        set_user_name: function(user_id) {
            this.set('user_id', user_id);
        },
        get_user_name: function() {
            return this.get('user_id');
        },
        set_journal: function(statement_ids) {
            this.set('statement_ids', statement_ids)
        },
        get_journal: function() {
            return this.get('statement_ids');
        },
        get_change: function(paymentline) {
            if (!paymentline) {
                if(this.get_total_paid() > 0 || this.get_cancel_order()){
                    var change = this.get_total_paid() - this.get_total_with_tax();
                }else{
                    var change = this.get_amount_return();
                }
            } else {
                var change = -this.get_total_with_tax(); 
                var lines  = this.pos.get_order().get_paymentlines();
                for (var i = 0; i < lines.length; i++) {
                    change += lines[i].get_amount();
                    if (lines[i] === paymentline) {
                        break;
                    }
                }
            }
            return round_pr(Math.max(0,change), this.pos.currency.rounding);
        },
        export_as_JSON: function() {
            var self = this;
        	var new_val = {};
            var orders = _super_Order.export_as_JSON.call(this);
            var cancel_orders = '';
            _.each(self.get_orderlines(), function(line){
                if(line.get_cancel_item()){
                    cancel_orders += " "+line.get_cancel_item();
                }
            });
            new_val = {
                old_order_id: this.get_order_id(),
                sequence: this.get_sequence(),
                pos_reference: this.get_pos_reference(),
                amount_due: this.get_due() ? this.get_due() : 0.00,
                reserved: this.get_reservation_mode() || false,
                delivery_date: this.get_delivery_date() || false,
                cancel_order_ref: cancel_orders || false,
                cancel_order: this.get_cancel_order() || false,
                set_as_draft: this.get_draft_order() || false,
                customer_email: this.get_client() ? this.get_client().email : false,
                fresh_order: this.get_fresh_order() || false,
                partial_pay: this.get_partial_pay() || false,
            }
            $.extend(orders, new_val);
            return orders;
        },
        export_for_printing: function(){
            var self = this;
            var orders = _super_Order.export_for_printing.call(this);
            var last_paid_amt = 0;
            var currentOrderLines = this.get_orderlines();
            if(currentOrderLines.length > 0) {
            	_.each(currentOrderLines,function(item) {
            		if(self.pos.config.enable_partial_payment &&
            				item.get_product().id == self.pos.config.prod_for_payment[0] ){
            			last_paid_amt = item.get_display_price()
            		}
                });
            }
            var total_paid_amt = this.get_total_paid()-last_paid_amt
            var new_val = {
            	reprint_payment: this.get_journal() || false,
            	ref: this.get_pos_reference() || false,
            	date_order: this.get_date_order() || false,
            	last_paid_amt: last_paid_amt || 0,
            	total_paid_amt: total_paid_amt || false,
            	amount_due: this.get_due() ? this.get_due() : 0.00,
            	old_order_id: this.get_order_id(),
            	delivery_date: moment(this.get_delivery_date()).format('L') || false,
            };
            $.extend(orders, new_val);
            return orders;
        },
        set_date_order: function(val){
        	this.set('date_order',val)
        },
        get_date_order: function(){
        	return this.get('date_order')
        },
        set_reservation_mode: function(mode){
            this.set('reservation_mode', mode)
        },
        get_reservation_mode: function(){
            return this.get('reservation_mode');
        },
        set_delivery_date: function(val){
            this.set('delivery_date', val)
        },
        get_delivery_date: function(){
            return this.get('delivery_date');
        },
        set_cancel_order: function(val){
            this.set('cancel_order', val)
        },
        get_cancel_order: function(){
            return this.get('cancel_order');
        },
        set_paying_due: function(val){
            this.set('paying_due', val)
        },
        get_paying_due: function(){
            return this.get('paying_due');
        },
        set_draft_order: function(val) {
            this.set('draft_order', val);
        },
        get_draft_order: function() {
            return this.get('draft_order');
        },
        set_cancellation_charges: function(val) {
            this.set('cancellation_charges', val);
        },
        get_cancellation_charges: function() {
            return this.get('cancellation_charges');
        },
        set_refund_amount: function(refund_amount) {
            this.set('refund_amount', refund_amount);
        },
        get_refund_amount: function() {
            return this.get('refund_amount');
        },
        set_fresh_order: function(fresh_order) {
            this.set('fresh_order', fresh_order);
        },
        get_fresh_order: function() {
            return this.get('fresh_order');
        },
        set_partial_pay: function(partial_pay) {
            this.set('partial_pay', partial_pay);
        },
        get_partial_pay: function() {
            return this.get('partial_pay');
        },
    });
    
	var _super_posmodel = models.PosModel;
	 models.PosModel = models.PosModel.extend({
		load_server_data: function(){
			var self = this;
			var loaded = _super_posmodel.prototype.load_server_data.call(this);
			loaded = loaded.then(function(){ 
				var date = new Date();
				var domain;
				var start_date;
				self.domain_order = []
				if(date){
                    if(self.config.last_days){
                        date.setDate(date.getDate() - self.config.last_days);
                    }
                    start_date = date.toJSON().slice(0,10);
                    self.domain_order.push(['create_date' ,'>=', start_date]);
                }
                self.domain_order.push(['state','in',['draft']])
                var params = {
                	model: 'pos.order',
                	method: 'ac_pos_search_read',
                	args: [{'domain': self.domain_order}],
                }
                return rpc.query(params, {async: false})
//    			return new Model('pos.order').get_func('ac_pos_search_read')(self.domain_order)
                .then(function(orders){
                	console.log("orders", orders);
                	self.db.add_orders(orders);
                    self.set({'pos_order_list' : orders});
                });
			});
			return loaded;
		},
		_save_to_server: function (orders, options) {
			var self = this;
			return _super_posmodel.prototype._save_to_server.apply(this, arguments)
			.then(function(server_ids){
				if(server_ids.length > 0 && self.config.enable_order_reservation){
					var params = {
						model: 'pos.order',
						method: 'ac_pos_search_read',
						args: [{'domain': [['id', 'in', server_ids]]}],
					}
					rpc.query(params, {async: false}).then(function(orders){
		                if(orders.length > 0){
		                	orders = orders[0];
		                    var exist_order = _.findWhere(self.get('pos_order_list'), {'pos_reference': orders.pos_reference})
		                    if(exist_order){
		                    	_.extend(exist_order, orders);
		                    } else {
		                    	self.get('pos_order_list').push(orders);
		                    }
		                    var new_orders = _.sortBy(self.get('pos_order_list'), 'id').reverse();
		                    self.db.add_orders(new_orders);
		                    self.set({ 'pos_order_list' : new_orders });
		                }
		            });
				}
			});
		},
//		_save_to_server: function (orders, options) {
//            if (!orders || !orders.length) {
//                var result = $.Deferred();
//                result.resolve([]);
//                return result;
//            }
//                
//            options = options || {};
//
//            var self = this;
//            var timeout = typeof options.timeout === 'number' ? options.timeout : 7500 * orders.length;
//
//            // we try to send the order. shadow prevents a spinner if it takes too long. (unless we are sending an invoice,
//            // then we want to notify the user that we are waiting on something )
//            var posOrderModel = new Model('pos.order');
//            return posOrderModel.call('create_from_ui',
//                [_.map(orders, function (order) {
//                    order.to_invoice = options.to_invoice || false;
//                    return order;
//                })],
//                undefined,
//                {
//                    shadow: !options.to_invoice,
//                    timeout: timeout
//                }
//            ).then(function (server_ids) {
//            	if(server_ids != []){
//            		new Model('pos.order').get_func('ac_pos_search_read')([['id', 'in', server_ids]])
//                    .then(function(orders){
//                        _.each(orders, function(order){
//                            if(order.fresh_order && self.config.enable_pos_welcome_mail){
//                                new Model('pos.order').call('send_reserve_mail', [order.id])
//                            }
//                        })
//                        var orders_data= self.get('pos_order_list');
//                        var new_orders = [];
//                        var flag = true;
//                        if(orders && orders[0]){
//                        	for(var i in orders_data){
//                        		if(orders_data[i].pos_reference == orders[0].pos_reference){
//                        			new_orders.push(orders[0])
//                        			flag = false
//                        		} else {
//                        			new_orders.push(orders_data[i])
//                        		}
//                        	}
//                        	if(flag){
//                        		new_orders = orders.concat(orders_data);
//                        	}
//                         self.db.add_orders(new_orders);
//                            self.set({'pos_order_list' : new_orders}); 
//                        } else {
//                        	new_orders = orders.concat(orders_data);
//                         self.db.add_orders(new_orders);
//                            self.set({'pos_order_list' : new_orders}); 
//                        }
//                    });
//               }
//                _.each(orders, function (order) {
//                    self.db.remove_order(order.id);
//                });
//                return server_ids;
//            }).fail(function (error, event){
//                if(error.code === 200 ){    // Business Logic Error, not a connection problem
//                	self.gui.show_popup('error-traceback',{
//                        message: error.data.message,
//                        comment: error.data.debug
//                    });
//                }
//                // prevent an error popup creation by the rpc failure
//                // we want the failure to be silent as we send the orders in the background
//                event.preventDefault();
//                console.error('Failed to send orders:', orders);
//            });
//        },
			//			New Code will be on add_partners
//        load_new_partners: function(){
//            var self = this;
//            var def  = new $.Deferred();
//            var fields = _.find(this.models,function(model){ return model.model === 'res.partner'; }).fields;
//            var domain = [['customer','=',true],['write_date','>',this.db.get_partner_write_date()]];
//            var context = {'timeout':3000, 'shadow': true};
//            rpc.query()
//            new Model('res.partner').call('search_read',
//            [domain, fields, 0, false, false, context], {}, { async: false })
//            .then(function(partners){
//                _.each(partners, function(partner){
//                    if(self.db.partner_by_id[partner.id]){
//                        var id = partner.id;
//                        delete self.db.partner_by_id[partner.id]
//                    }
//                });
//                if (self.db.add_partners(partners)) {   // check if the partners we got were real updates
//                    def.resolve();
//                } else {
//                    def.reject();
//                }
//            }, function(err,event){ event.preventDefault(); def.reject(); });
//            return def;
//        },
	});	

    var _super_orderline = models.Orderline.prototype;
    models.Orderline = models.Orderline.extend({
        initialize: function(attr,options){
            this.cancel_item = false;
            this.consider_qty = 0;
            _super_orderline.initialize.call(this, attr, options);
        },
        set_cancel_item: function(val){
            this.set('cancel_item', val)
        },
        get_cancel_item: function(){
            return this.get('cancel_item');
        },
        set_consider_qty: function(val){
            this.set('consider_qty', val)
        },
        get_consider_qty: function(){
            return this.get('consider_qty');
        },
        export_as_JSON: function() {
        	var new_val = {};
            var orderlines = _super_orderline.export_as_JSON.call(this);
            new_val = {
                cancel_item: this.get_cancel_item() || false,
                cancel_process: this.get_cancel_process() || false,
                cancel_qty: this.get_quantity() || false,
                consider_qty : this.get_consider_qty(),
                cancel_item_id: this.get_cancel_item_id() || false,
                new_line_status: this.get_line_status() || false,
            }
            $.extend(orderlines, new_val);
            return orderlines;
        },
        set_cancel_process: function(oid) {
            this.set('cancel_process', oid)
        },
        get_cancel_process: function() {
            return this.get('cancel_process');
        },
        set_cancel_item_id: function(val) {
            this.set('cancel_item_id', val)
        },
        get_cancel_item_id: function() {
            return this.get('cancel_item_id');
        },
        set_line_status: function(val) {
            this.set('line_status', val)
        },
        get_line_status: function() {
            return this.get('line_status');
        },
    });

})