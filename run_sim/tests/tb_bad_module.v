`timescale 1ns/1ps
// 案例③专用：testbench 里例化了一个根本不存在的模块 nonexistent_mod
// （不提供任何对应的 .v 文件），用来触发 “Unknown module type”
module tb_bad_module;
    reg  a, b;
    wire y;
    nonexistent_mod u_missing (.a(a), .b(b), .y(y));
    initial begin
        $dumpfile("waves/bad_module.vcd");
        $dumpvars(0, tb_bad_module);
        a = 0; b = 0; #10;
        $finish;
    end
endmodule
