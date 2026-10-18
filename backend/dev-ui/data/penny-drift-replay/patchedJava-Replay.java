public final class Replay {
    public static void main(String[] args) {
        System.out.print(new FxWireService().calculate(new java.math.BigDecimal(args[0]), new java.math.BigDecimal(args[1])).toPlainString());
    }
}
