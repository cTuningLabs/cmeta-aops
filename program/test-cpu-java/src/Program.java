
import java.io.FileWriter;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

public class Program {
    // Write stats to JSON file (like C version)
    static boolean writeStatsJson(String dtype, int m, int n, int k, int repeat, int clean, long seed,
                                  double minMatmul, double maxMatmul, double[] allMatmul,
                                  double minDataPrep, double maxDataPrep, double[] allDataPrep,
                                  double minSum, double maxSum, double[] allSum,
                                  double minTotal, double maxTotal, double[] allTotal,
                                  double aggregatedValue) {
        try (FileWriter json = new FileWriter("tmp-cmeta-program-stats.json")) {
            json.write("{\n");
            json.write("  \"input\": {\n");
            json.write(String.format("    \"dtype\": \"%s\",\n", dtype));
            json.write(String.format("    \"M\": %d,\n", m));
            json.write(String.format("    \"N\": %d,\n", n));
            json.write(String.format("    \"K\": %d,\n", k));
            json.write(String.format("    \"repeat\": %d,\n", repeat));
            json.write(String.format("    \"clean\": %d,\n", clean));
            json.write(String.format("    \"seed\": %d\n", seed));
            json.write("  },\n");
            json.write(String.format("  \"aggregated_value\": %.12f,\n", aggregatedValue));
            json.write("  \"timing\": {\n");

            json.write("    \"matmul_time\": {\n");
            json.write(String.format("      \"min\": %.12f,\n", minMatmul));
            json.write(String.format("      \"max\": %.12f,\n", maxMatmul));
            json.write("      \"all\": [");
            for (int i = 0; i < repeat; ++i) {
                json.write((i == 0 ? "" : ", ") + String.format("%.12f", allMatmul[i]));
            }
            json.write("]\n");
            json.write("    },\n");

            json.write("    \"data_prep\": {\n");
            json.write(String.format("      \"min\": %.12f,\n", minDataPrep));
            json.write(String.format("      \"max\": %.12f,\n", maxDataPrep));
            json.write("      \"all\": [");
            for (int i = 0; i < repeat; ++i) {
                json.write((i == 0 ? "" : ", ") + String.format("%.12f", allDataPrep[i]));
            }
            json.write("]\n");
            json.write("    },\n");

            json.write("    \"sum\": {\n");
            json.write(String.format("      \"min\": %.12f,\n", minSum));
            json.write(String.format("      \"max\": %.12f,\n", maxSum));
            json.write("      \"all\": [");
            for (int i = 0; i < repeat; ++i) {
                json.write((i == 0 ? "" : ", ") + String.format("%.12f", allSum[i]));
            }
            json.write("]\n");
            json.write("    },\n");

            json.write("    \"total\": {\n");
            json.write(String.format("      \"min\": %.12f,\n", minTotal));
            json.write(String.format("      \"max\": %.12f,\n", maxTotal));
            json.write("      \"all\": [");
            for (int i = 0; i < repeat; ++i) {
                json.write((i == 0 ? "" : ", ") + String.format("%.12f", allTotal[i]));
            }
            json.write("]\n");
            json.write("    }\n");

            json.write("  }\n");
            json.write("}\n");
            return true;
        } catch (IOException e) {
            return false;
        }
    }
        // Thread test similar to OpenMP
        static void threadTest() {
            int maxThreads = Runtime.getRuntime().availableProcessors();
            System.out.println("==================================================================");
            System.out.println("Testing Java threads ...\n");
            System.out.println("max threads = " + maxThreads);

            ExecutorService pool = Executors.newFixedThreadPool(maxThreads);
            for (int i = 0; i < maxThreads; ++i) {
                final int threadNum = i;
                pool.submit(() -> {
                    System.out.println("hello from thread " + threadNum + " of " + maxThreads);
                });
            }
            pool.shutdown();
            try { pool.awaitTermination(1, TimeUnit.SECONDS); } catch (InterruptedException e) {}
            System.out.println();
        }

        // SSL/Crypto test similar to OpenSSL
        static void sslTest() {
            System.out.println("==================================================================");
            System.out.println("Testing Java SSL/Crypto ...\n");
            System.out.println("Java version: " + System.getProperty("java.version"));

            try {
                String msg = "hello world";
                MessageDigest digest = MessageDigest.getInstance("SHA-256");
                byte[] hash = digest.digest(msg.getBytes());
                System.out.print("SHA256(\"hello world\") = ");
                for (byte b : hash) System.out.printf("%02x", b);
                System.out.println();
            } catch (NoSuchAlgorithmException e) {
                System.out.println("SHA-256 not supported");
            }
            System.out.println();
        }
    enum DType {
        FLOAT32, FLOAT64, INT64, INT32, INT16, INT8
    }

    static double nowSeconds() {
        return System.nanoTime() / 1e9;
    }

    static void fillRandom(float[] arr, Random rnd) {
        for (int i = 0; i < arr.length; ++i) arr[i] = rnd.nextFloat();
    }
    static void fillRandom(double[] arr, Random rnd) {
        for (int i = 0; i < arr.length; ++i) arr[i] = rnd.nextDouble();
    }
    static void fillRandom(long[] arr, Random rnd) {
        for (int i = 0; i < arr.length; ++i) arr[i] = rnd.nextInt(16);
    }
    static void fillRandom(int[] arr, Random rnd) {
        for (int i = 0; i < arr.length; ++i) arr[i] = rnd.nextInt(16);
    }
    static void fillRandom(short[] arr, Random rnd) {
        for (int i = 0; i < arr.length; ++i) arr[i] = (short)rnd.nextInt(16);
    }
    static void fillRandom(byte[] arr, Random rnd) {
        for (int i = 0; i < arr.length; ++i) arr[i] = (byte)rnd.nextInt(16);
    }

    static double sum(float[] arr) {
        double s = 0.0;
        for (float v : arr) s += v;
        return s;
    }
    static double sum(double[] arr) {
        double s = 0.0;
        for (double v : arr) s += v;
        return s;
    }
    static double sum(long[] arr) {
        double s = 0.0;
        for (long v : arr) s += v;
        return s;
    }
    static double sum(int[] arr) {
        double s = 0.0;
        for (int v : arr) s += v;
        return s;
    }
    static double sum(short[] arr) {
        double s = 0.0;
        for (short v : arr) s += v;
        return s;
    }
    static double sum(byte[] arr) {
        double s = 0.0;
        for (byte v : arr) s += v;
        return s;
    }

    public static void main(String[] args) {
        threadTest();
        sslTest();
        if (args.length < 3) {
            System.out.println("Usage: java Program [dtype] M N K [repeat] [clean] [seed]");
            return;
        }
        int argi = 0;
        DType dtype = DType.FLOAT32;
        String dtypeName = "float32";
        if (!isInteger(args[argi])) {
            switch (args[argi].toLowerCase()) {
                case "float32": case "f32": dtype = DType.FLOAT32; dtypeName = "float32"; break;
                case "float64": case "f64": case "double": dtype = DType.FLOAT64; dtypeName = "float64"; break;
                case "int64": case "i64": dtype = DType.INT64; dtypeName = "int64"; break;
                case "int32": case "i32": dtype = DType.INT32; dtypeName = "int32"; break;
                case "int16": case "i16": dtype = DType.INT16; dtypeName = "int16"; break;
                case "int8": case "i8": dtype = DType.INT8; dtypeName = "int8"; break;
                default:
                    System.err.println("Error: unsupported dtype '" + args[argi] + "'.");
                    return;
            }
            ++argi;
        }
        if (args.length - argi < 3) {
            System.err.println("Error: M N K are required.");
            return;
        }
        int m = Integer.parseInt(args[argi++]);
        int n = Integer.parseInt(args[argi++]);
        int k = Integer.parseInt(args[argi++]);
        int repeat = 1;
        int clean = 0;
        long seed = System.currentTimeMillis();
        if (argi < args.length) repeat = Integer.parseInt(args[argi++]);
        if (argi < args.length) clean = parseClean(args[argi++]);
        if (argi < args.length) seed = Long.parseLong(args[argi++]);
        if (argi != args.length) {
            System.err.println("Error: too many arguments.");
            return;
        }
        int aCount = m * n, bCount = n * k, cCount = m * k;
        double[] timesMatmul = new double[repeat];
        double[] timesDataPrep = new double[repeat];
        double[] timesSum = new double[repeat];
        double[] timesTotal = new double[repeat];
        double minMatmul = Double.MAX_VALUE, maxMatmul = 0.0;
        double minDataPrep = Double.MAX_VALUE, maxDataPrep = 0.0;
        double minSum = Double.MAX_VALUE, maxSum = 0.0;
        double minTotal = Double.MAX_VALUE, maxTotal = 0.0;
        double aggregatedValue = 0.0;
        Random rnd = new Random(seed);
        for (int r = 0; r < repeat; ++r) {
            double totalT0 = nowSeconds();
            double dataPrepDt = 0.0;
            double t0;
            switch (dtype) {
                case FLOAT32: {
                    float[] a = new float[aCount];
                    float[] b = new float[bCount];
                    float[] c = new float[cCount];
                    fillRandom(a, rnd); fillRandom(b, rnd);
                    if (clean != 0) {
                        double prepT0 = nowSeconds();
                        fillRandom(a, rnd); fillRandom(b, rnd);
                        dataPrepDt = nowSeconds() - prepT0;
                    }
                    t0 = nowSeconds();
                    Matmul.matmulF32(a, b, c, m, n, k);
                    double matmulDt = nowSeconds() - t0;
                    t0 = nowSeconds();
                    aggregatedValue += sum(c);
                    double sumDt = nowSeconds() - t0;
                    double totalDt = nowSeconds() - totalT0;
                    timesDataPrep[r] = dataPrepDt;
                    timesMatmul[r] = matmulDt;
                    timesSum[r] = sumDt;
                    timesTotal[r] = totalDt;
                    minDataPrep = Math.min(minDataPrep, dataPrepDt);
                    maxDataPrep = Math.max(maxDataPrep, dataPrepDt);
                    minMatmul = Math.min(minMatmul, matmulDt);
                    maxMatmul = Math.max(maxMatmul, matmulDt);
                    minSum = Math.min(minSum, sumDt);
                    maxSum = Math.max(maxSum, sumDt);
                    minTotal = Math.min(minTotal, totalDt);
                    maxTotal = Math.max(maxTotal, totalDt);
                    break;
                }
                case FLOAT64: {
                    double[] a = new double[aCount];
                    double[] b = new double[bCount];
                    double[] c = new double[cCount];
                    fillRandom(a, rnd); fillRandom(b, rnd);
                    if (clean != 0) {
                        double prepT0 = nowSeconds();
                        fillRandom(a, rnd); fillRandom(b, rnd);
                        dataPrepDt = nowSeconds() - prepT0;
                    }
                    t0 = nowSeconds();
                    Matmul.matmulF64(a, b, c, m, n, k);
                    double matmulDt = nowSeconds() - t0;
                    t0 = nowSeconds();
                    aggregatedValue += sum(c);
                    double sumDt = nowSeconds() - t0;
                    double totalDt = nowSeconds() - totalT0;
                    timesDataPrep[r] = dataPrepDt;
                    timesMatmul[r] = matmulDt;
                    timesSum[r] = sumDt;
                    timesTotal[r] = totalDt;
                    minDataPrep = Math.min(minDataPrep, dataPrepDt);
                    maxDataPrep = Math.max(maxDataPrep, dataPrepDt);
                    minMatmul = Math.min(minMatmul, matmulDt);
                    maxMatmul = Math.max(maxMatmul, matmulDt);
                    minSum = Math.min(minSum, sumDt);
                    maxSum = Math.max(maxSum, sumDt);
                    minTotal = Math.min(minTotal, totalDt);
                    maxTotal = Math.max(maxTotal, totalDt);
                    break;
                }
                case INT64: {
                    long[] a = new long[aCount];
                    long[] b = new long[bCount];
                    long[] c = new long[cCount];
                    fillRandom(a, rnd); fillRandom(b, rnd);
                    if (clean != 0) {
                        double prepT0 = nowSeconds();
                        fillRandom(a, rnd); fillRandom(b, rnd);
                        dataPrepDt = nowSeconds() - prepT0;
                    }
                    t0 = nowSeconds();
                    Matmul.matmulI64(a, b, c, m, n, k);
                    double matmulDt = nowSeconds() - t0;
                    t0 = nowSeconds();
                    aggregatedValue += sum(c);
                    double sumDt = nowSeconds() - t0;
                    double totalDt = nowSeconds() - totalT0;
                    timesDataPrep[r] = dataPrepDt;
                    timesMatmul[r] = matmulDt;
                    timesSum[r] = sumDt;
                    timesTotal[r] = totalDt;
                    minDataPrep = Math.min(minDataPrep, dataPrepDt);
                    maxDataPrep = Math.max(maxDataPrep, dataPrepDt);
                    minMatmul = Math.min(minMatmul, matmulDt);
                    maxMatmul = Math.max(maxMatmul, matmulDt);
                    minSum = Math.min(minSum, sumDt);
                    maxSum = Math.max(maxSum, sumDt);
                    minTotal = Math.min(minTotal, totalDt);
                    maxTotal = Math.max(maxTotal, totalDt);
                    break;
                }
                case INT32: {
                    int[] a = new int[aCount];
                    int[] b = new int[bCount];
                    int[] c = new int[cCount];
                    fillRandom(a, rnd); fillRandom(b, rnd);
                    if (clean != 0) {
                        double prepT0 = nowSeconds();
                        fillRandom(a, rnd); fillRandom(b, rnd);
                        dataPrepDt = nowSeconds() - prepT0;
                    }
                    t0 = nowSeconds();
                    Matmul.matmulI32(a, b, c, m, n, k);
                    double matmulDt = nowSeconds() - t0;
                    t0 = nowSeconds();
                    aggregatedValue += sum(c);
                    double sumDt = nowSeconds() - t0;
                    double totalDt = nowSeconds() - totalT0;
                    timesDataPrep[r] = dataPrepDt;
                    timesMatmul[r] = matmulDt;
                    timesSum[r] = sumDt;
                    timesTotal[r] = totalDt;
                    minDataPrep = Math.min(minDataPrep, dataPrepDt);
                    maxDataPrep = Math.max(maxDataPrep, dataPrepDt);
                    minMatmul = Math.min(minMatmul, matmulDt);
                    maxMatmul = Math.max(maxMatmul, matmulDt);
                    minSum = Math.min(minSum, sumDt);
                    maxSum = Math.max(maxSum, sumDt);
                    minTotal = Math.min(minTotal, totalDt);
                    maxTotal = Math.max(maxTotal, totalDt);
                    break;
                }
                case INT16: {
                    short[] a = new short[aCount];
                    short[] b = new short[bCount];
                    short[] c = new short[cCount];
                    fillRandom(a, rnd); fillRandom(b, rnd);
                    if (clean != 0) {
                        double prepT0 = nowSeconds();
                        fillRandom(a, rnd); fillRandom(b, rnd);
                        dataPrepDt = nowSeconds() - prepT0;
                    }
                    t0 = nowSeconds();
                    Matmul.matmulI16(a, b, c, m, n, k);
                    double matmulDt = nowSeconds() - t0;
                    t0 = nowSeconds();
                    aggregatedValue += sum(c);
                    double sumDt = nowSeconds() - t0;
                    double totalDt = nowSeconds() - totalT0;
                    timesDataPrep[r] = dataPrepDt;
                    timesMatmul[r] = matmulDt;
                    timesSum[r] = sumDt;
                    timesTotal[r] = totalDt;
                    minDataPrep = Math.min(minDataPrep, dataPrepDt);
                    maxDataPrep = Math.max(maxDataPrep, dataPrepDt);
                    minMatmul = Math.min(minMatmul, matmulDt);
                    maxMatmul = Math.max(maxMatmul, matmulDt);
                    minSum = Math.min(minSum, sumDt);
                    maxSum = Math.max(maxSum, sumDt);
                    minTotal = Math.min(minTotal, totalDt);
                    maxTotal = Math.max(maxTotal, totalDt);
                    break;
                }
                case INT8: {
                    byte[] a = new byte[aCount];
                    byte[] b = new byte[bCount];
                    byte[] c = new byte[cCount];
                    fillRandom(a, rnd); fillRandom(b, rnd);
                    if (clean != 0) {
                        double prepT0 = nowSeconds();
                        fillRandom(a, rnd); fillRandom(b, rnd);
                        dataPrepDt = nowSeconds() - prepT0;
                    }
                    t0 = nowSeconds();
                    Matmul.matmulI8(a, b, c, m, n, k);
                    double matmulDt = nowSeconds() - t0;
                    t0 = nowSeconds();
                    aggregatedValue += sum(c);
                    double sumDt = nowSeconds() - t0;
                    double totalDt = nowSeconds() - totalT0;
                    timesDataPrep[r] = dataPrepDt;
                    timesMatmul[r] = matmulDt;
                    timesSum[r] = sumDt;
                    timesTotal[r] = totalDt;
                    minDataPrep = Math.min(minDataPrep, dataPrepDt);
                    maxDataPrep = Math.max(maxDataPrep, dataPrepDt);
                    minMatmul = Math.min(minMatmul, matmulDt);
                    maxMatmul = Math.max(maxMatmul, matmulDt);
                    minSum = Math.min(minSum, sumDt);
                    maxSum = Math.max(maxSum, sumDt);
                    minTotal = Math.min(minTotal, totalDt);
                    maxTotal = Math.max(maxTotal, totalDt);
                    break;
                }
            }
        }
        System.out.println("Input:");
        System.out.println("  dtype  = " + dtypeName);
        System.out.println("  M N K  = " + m + " " + n + " " + k);
        System.out.println("  repeat = " + repeat);
        System.out.println("  clean  = " + clean);
        System.out.println("  seed   = " + seed);
        System.out.printf("  aggregated_value = %.12f\n", aggregatedValue);
        System.out.println("\nTiming (seconds):");
        System.out.printf("  matmul_time min = %.9f, max = %.9f\n", minMatmul, maxMatmul);
        System.out.printf("  data_prep   min = %.9f, max = %.9f\n", minDataPrep, maxDataPrep);
        System.out.printf("  sum         min = %.9f, max = %.9f\n", minSum, maxSum);
        System.out.printf("  total       min = %.9f, max = %.9f\n", minTotal, maxTotal);

        System.out.println("==================================================================");
        System.out.println("Writing stats for cMeta ...\n");
        if (!writeStatsJson(dtypeName, m, n, k, repeat, clean, seed, minMatmul, maxMatmul, timesMatmul, minDataPrep, maxDataPrep, timesDataPrep, minSum, maxSum, timesSum, minTotal, maxTotal, timesTotal, aggregatedValue)) {
            System.err.println("Warning: could not write tmp-cmeta-program-stats.json");
        } else {
            System.out.println("Wrote tmp-cmeta-program-stats.json");
        }
    }

    static boolean isInteger(String s) {
        try { Integer.parseInt(s); return true; } catch (Exception e) { return false; }
    }
    static int parseClean(String s) {
        if (s.equals("0") || s.equalsIgnoreCase("false") || s.equalsIgnoreCase("no")) return 0;
        if (s.equals("1") || s.equalsIgnoreCase("true") || s.equalsIgnoreCase("yes")) return 1;
        return 0;
    }
}
