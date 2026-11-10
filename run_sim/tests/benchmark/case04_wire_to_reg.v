// 规则④ wire_to_reg 测试样例：wire 在 always 块里被过程赋值
// iverilog 报 "not a valid l-value"
module wirereg_demo (
    input  wire clk,
    input  wire rst_n,
    output wire [7:0] q
);
    reg [7:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q <= 8'h0;
        else
            q <= cnt;
    end
endmodule
