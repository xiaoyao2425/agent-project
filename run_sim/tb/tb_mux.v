`timescale 1ns/1ps
module tb_mux;
    reg a, b, sel;
    wire y;
    mux u_mux (.a(a), .b(b), .sel(sel), .y(y));
    initial begin
        $dumpfile("waves/mux.vcd");
        $dumpvars(0, tb_mux);
        $monitor("time=%0t, a=%b, b=%b, sel=%b, y=%b", $time, a, b, sel, y);
        a=0; b=0; sel=0; #10;
        a=1; b=0; sel=0; #10;
        a=0; b=1; sel=0; #10;
        a=1; b=1; sel=1; #10;
        a=0; b=0; sel=1; #10;
        $finish;
    end
endmodule
