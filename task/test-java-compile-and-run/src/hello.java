public class hello {
    public static void main(String[] args) {
        System.out.println("Hello, World!\n");

        System.out.println("Arguments:");

        for (int i = 0; i < args.length; i++) {
            System.out.println("arg[" + i + "] = " + args[i]);
        }
    }
}
