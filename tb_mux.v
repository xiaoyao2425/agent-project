cat > tb_mux.v << 'EOF'
`timescale 1ns/1ps
module tb_mux;
    reg a, b, sel;
    wire y;
    mux2x1 uut (.a(a), .b(b), .sel(sel), .y(y));

    initial begin
        $dumpfile("mux.vcd");
        $dumpvars(0, tb_mux);
        $monitor("时间=%0t, sel=%b, a=%b, b=%b -> y=%b", $time, sel, a, b, y);
        {a, b, sel} = 3'b000; #10;
        {a, b, sel} = 3'b001; #10;
        {a, b, sel} = 3'b010; #10;
        {a, b, sel} = 3'b011; #10;
        {a, b, sel} = 3'b100; #10;
        {a, b, sel} = 3'b101; #10;
        {a, b, sel} = 3'b110; #10;
        {a, b, sel} = 3'b111; #10;
        $finish;
    end
endmodule
EOF