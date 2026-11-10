// case06：完全正确的代码 —— auto_fix 应返回 already_ok，一个字节都不许动
module clean_demo (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] d,
    output reg  [7:0] q
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q <= 8'h0;
        else
            q <= d;
    end
endmodule
