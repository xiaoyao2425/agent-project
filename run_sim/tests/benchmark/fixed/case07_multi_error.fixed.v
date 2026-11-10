// case07：复合错误 —— always @(*)（SV语法）+ 漏分号，两条规则要接力
// 测的是多规则协作：sv_to_2001 先转，missing_semicolon 后补
module multi_demo (
    input  wire [7:0] a,
    input  wire [7:0] b,
    output wire [7:0] y
);
    reg [7:0] tmp;
    always @(*) begin
        tmp = a & b;// BUG1: 漏分号

    end
    assign y = tmp;
endmodule
