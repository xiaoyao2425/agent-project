`timescale 1ns/1ps
// 案例②的 testbench：例化上面那个“少分号”的模块
module tb_bad_syntax;
    reg  a, b;
    wire y;
    bad_syntax u_dut (.a(a), .b(b), .y(y));
    initial begin
        $dumpfile("waves/bad_syntax.vcd");
        $dumpvars(0, tb_bad_syntax);
        a = 0; b = 0; #10;
        a = 1; b = 1; #10;
        $finish;
    end
endmodule
