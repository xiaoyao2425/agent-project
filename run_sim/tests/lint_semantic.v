// 语义级 Lint 测试样例（iverilog 查不出，verilator 应报 WIDTH/UNUSEDSIGNAL/UNDRIVEN）
// 预期 verilator 结果：
//   - WIDTHEXPAND/WIDTHTRUNC: 位宽不匹配（4bit 信号被赋 8bit 值）
//   - UNUSEDSIGNAL: unused_sig 声明了没用
//   - UNDRIVEN: undriven_sig 没有驱动源
module lint_semantic (
    input  wire [3:0] a,
    input  wire [3:0] b,
    output wire [3:0] sum_o
);
    wire [3:0] narrow;      // UNUSEDSIGNAL: 未使用
    wire [7:0] wide;        // UNDRIVEN: 无驱动
    wire        unused_sig;

    assign sum_o   = a + b + 8'hFF;   // WIDTH: 8bit 常量加进 4bit 表达式
    assign narrow  = {a, b};          // WIDTHTRUNC: 8bit 拼接塞进 4bit

endmodule
