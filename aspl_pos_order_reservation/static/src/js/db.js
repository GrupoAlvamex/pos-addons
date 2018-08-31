odoo.define('aspl_pos_order_reservation.db', function (require) {

	var DB = require('point_of_sale.DB');
	DB.include({
		init: function(options){
        	this._super.apply(this, arguments);
        	this.group_products = [];
        	this.order_write_date = null;
        	this.order_by_id = {};
        	this.line_by_id = {};
        	this.order_sorted = [];
        	this.order_search_string = "";
        	this.line_search_string = ""
        },
        add_orders: function(orders){
            var updated_count = 0;
            var new_write_date = '';
            for(var i = 0, len = orders.length; i < len; i++){
                var order = orders[i];
                if (    this.order_write_date && 
                        this.order_by_id[order.id] &&
                        new Date(this.order_write_date).getTime() + 1000 >=
                        new Date(order.write_date).getTime() ) {
                    continue;
                } else if ( new_write_date < order.write_date ) { 
                    new_write_date  = order.write_date;
                }
                if (!this.order_by_id[order.id]) {
                    this.order_sorted.push(order.id);
                }
                this.order_by_id[order.id] = order;
                updated_count += 1;
            }
            this.order_write_date = new_write_date || this.order_write_date;
            if (updated_count) {
                // If there were updates, we need to completely 
                this.order_search_string = "";
                for (var id in this.order_by_id) {
                    var order = this.order_by_id[id];
                    this.order_search_string += this._order_search_string(order);
                }
            }
            return updated_count;
        },
        _order_search_string: function(order){
            var str =  order.name;
            if(order.pos_reference){
                str += '|' + order.pos_reference;
            }
            if(order.partner_id){
            	var partner = this.get_partner_by_id(order.partner_id[0]);
            	if(partner)
            		str += '|' + partner.name;
            }
            str = '' + order.id + ':' + str.replace(':','') + '\n';
            return str;
        },
        get_order_write_date: function(){
            return this.order_write_date;
        },
        get_order_by_id: function(id){
            return this.order_by_id[id];
        },
        search_order: function(query){
            try {
                query = query.replace(/[\[\]\(\)\+\*\?\.\-\!\&\^\$\|\~\_\{\}\:\,\\\/]/g,'.');
                query = query.replace(' ','.+');
                var re = RegExp("([0-9]+):.*?"+query,"gi");
            }catch(e){
                return [];
            }
            var results = [];
            var r;
            for(var i = 0; i < this.limit; i++){
                r = re.exec(this.order_search_string);
                if(r){
                    var id = Number(r[1]);
                    results.push(this.get_order_by_id(id));
                }else{
                    break;
                }
            }
            return results;
        },
        add_reserved_items: function(lines){
        	for(var i = 0, len = lines.length; i < len; i++){
        		var line = lines[i];
        		this.line_search_string += this._line_search_string(line);
        		this.line_by_id[line.id] = line
        	}
        },
        _line_search_string: function(line){
        	var str =  line.name;
        	if(line.product_id.length > 0){
                str += '|' + line.product_id[1];
            }
        	if(line.order_id.length > 0){
                str += '|' + line.order_id[1];
            }
        	str = '' + line.id + ':' + str.replace(':','') + '\n';
            return str;
        },
        search_item: function(query){
            try {
                query = query.replace(/[\[\]\(\)\+\*\?\.\-\!\&\^\$\|\~\_\{\}\:\,\\\/]/g,'.');
                query = query.replace(' ','.+');
                var re = RegExp("([0-9]+):.*?"+query,"gi");
            }catch(e){
                return [];
            }
            var results = [];
            var r;
            for(var i = 0; i < this.limit; i++){
                r = re.exec(this.line_search_string);
                if(r){
                    var id = Number(r[1]);
                    results.push(this.line_by_id[id]);
                }else{
                    break;
                }
            }
            return results;
        },
	});
});