public final class Replay {
    public static void main(String[] args) {
        System.out.print(new FxWireService().calculate(Double.parseDouble(args[0]), Double.parseDouble(args[1])).toPlainString());
    }
}
