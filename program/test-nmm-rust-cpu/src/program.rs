// Copyright (C) 2026 Grigori Fursin and cTuning Labs.
//
// Licensed under the Apache License, Version 2.0.
// See the COPYRIGHT and LICENSE files in the project root for details.
//
// Developed with the help of GitHub Copilot.

use std::env;
use std::time::{Duration, Instant};
use std::time::{SystemTime, UNIX_EPOCH};
use std::thread;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

struct SimpleRng {
    state: u64,
}

impl SimpleRng {
    fn new(seed: u64) -> Self {
        Self { state: seed.wrapping_add(0x9e3779b97f4a7c15) }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^ (z >> 31)
    }

    fn next_f32(&mut self) -> f32 {
        let v = self.next_u64() >> 40;
        (v as f32) / ((1u64 << 24) as f32)
    }

    fn next_f64(&mut self) -> f64 {
        let v = self.next_u64() >> 11;
        (v as f64) / ((1u64 << 53) as f64)
    }

    fn range_inclusive_i64(&mut self, min_val: i64, max_val: i64) -> i64 {
        let span = (max_val - min_val + 1) as u64;
        min_val + (self.next_u64() % span) as i64
    }
}

fn matmul_f32(a: &[f32], b: &[f32], c: &mut [f32], m: usize, n: usize, k: usize) {
    for i in 0..m {
        for j in 0..k {
            let mut sum = 0.0f32;
            for p in 0..n {
                sum += a[i * n + p] * b[p * k + j];
            }
            c[i * k + j] = sum;
        }
    }
}

fn matmul_f64(a: &[f64], b: &[f64], c: &mut [f64], m: usize, n: usize, k: usize) {
    for i in 0..m {
        for j in 0..k {
            let mut sum = 0.0f64;
            for p in 0..n {
                sum += a[i * n + p] * b[p * k + j];
            }
            c[i * k + j] = sum;
        }
    }
}

fn matmul_i64(a: &[i64], b: &[i64], c: &mut [i64], m: usize, n: usize, k: usize) {
    for i in 0..m {
        for j in 0..k {
            let mut sum = 0i64;
            for p in 0..n {
                sum += a[i * n + p] * b[p * k + j];
            }
            c[i * k + j] = sum;
        }
    }
}

fn matmul_i32(a: &[i32], b: &[i32], c: &mut [i32], m: usize, n: usize, k: usize) {
    for i in 0..m {
        for j in 0..k {
            let mut sum = 0i64;
            for p in 0..n {
                sum += a[i * n + p] as i64 * b[p * k + j] as i64;
            }
            c[i * k + j] = sum as i32;
        }
    }
}

fn matmul_i16(a: &[i16], b: &[i16], c: &mut [i16], m: usize, n: usize, k: usize) {
    for i in 0..m {
        for j in 0..k {
            let mut sum = 0i64;
            for p in 0..n {
                sum += a[i * n + p] as i64 * b[p * k + j] as i64;
            }
            c[i * k + j] = sum as i16;
        }
    }
}

fn matmul_i8(a: &[i8], b: &[i8], c: &mut [i8], m: usize, n: usize, k: usize) {
    for i in 0..m {
        for j in 0..k {
            let mut sum = 0i64;
            for p in 0..n {
                sum += a[i * n + p] as i64 * b[p * k + j] as i64;
            }
            c[i * k + j] = sum as i8;
        }
    }
}

fn sum_matrix_f32(mat: &[f32]) -> f64 {
    mat.iter().map(|&x| x as f64).sum()
}
fn sum_matrix_f64(mat: &[f64]) -> f64 {
    mat.iter().sum()
}
fn sum_matrix_i64(mat: &[i64]) -> f64 {
    mat.iter().map(|&x| x as f64).sum()
}
fn sum_matrix_i32(mat: &[i32]) -> f64 {
    mat.iter().map(|&x| x as f64).sum()
}
fn sum_matrix_i16(mat: &[i16]) -> f64 {
    mat.iter().map(|&x| x as f64).sum()
}
fn sum_matrix_i8(mat: &[i8]) -> f64 {
    mat.iter().map(|&x| x as f64).sum()
}

fn fill_random_f32(mat: &mut [f32], rng: &mut SimpleRng) {
    for x in mat.iter_mut() {
        *x = rng.next_f32();
    }
}
fn fill_random_f64(mat: &mut [f64], rng: &mut SimpleRng) {
    for x in mat.iter_mut() {
        *x = rng.next_f64();
    }
}
fn fill_random_i64(mat: &mut [i64], rng: &mut SimpleRng) {
    for x in mat.iter_mut() {
        *x = rng.range_inclusive_i64(0, 15);
    }
}
fn fill_random_i32(mat: &mut [i32], rng: &mut SimpleRng) {
    for x in mat.iter_mut() {
        *x = rng.range_inclusive_i64(0, 15) as i32;
    }
}
fn fill_random_i16(mat: &mut [i16], rng: &mut SimpleRng) {
    for x in mat.iter_mut() {
        *x = rng.range_inclusive_i64(0, 15) as i16;
    }
}
fn fill_random_i8(mat: &mut [i8], rng: &mut SimpleRng) {
    for x in mat.iter_mut() {
        *x = rng.range_inclusive_i64(0, 15) as i8;
    }
}

fn test_threads() {
    let nthreads = thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    println!("==================================================================");
    println!("Testing threads ...");
    println!("max threads = {}", nthreads);
    let mut handles = vec![];
    let nthreads = nthreads.min(16); // limit for demo
    for tid in 0..nthreads {
        handles.push(thread::spawn(move || {
            println!("hello from thread {} of {}", tid, nthreads);
        }));
    }
    for h in handles { h.join().unwrap(); }
    println!("");
}

fn test_crypto() {
    println!("==================================================================");
    println!("Testing built-in hash demo ...");
    let msg = b"hello world";
    let mut hasher = DefaultHasher::new();
    msg.hash(&mut hasher);
    println!("hash(\"hello world\") = {:016x}", hasher.finish());
}

fn test_math() {
    println!("==================================================================");
    println!("Testing basic math ...");
    let x = 16.0f64;
    println!("sqrt({:.2}) = {:.2}", x, x.sqrt());
    println!("sin(0.0) = {:.2}", 0.0f64.sin());
    println!("pow(2.0, 3.0) = {:.2}", 2.0f64.powf(3.0));
    println!("");
}

fn print_usage(prog: &str) {
    println!("Usage:\n  {} [dtype] M N K [repeat] [clean] [seed]", prog);
    println!("");
    println!("Arguments:");
    println!("  dtype  : float32 (default), float64, int64, int32, int16, int8");
    println!("  M,N,K  : positive integers for (M x N) * (N x K)");
    println!("  repeat : positive integer, default 1");
    println!("  clean  : 0/1 (or false/true), default 0");
    println!("  seed   : non-negative integer for RNG, default time");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let mut dtype = "float32";
    let mut repeat = 1usize;
    let mut clean = false;
    let mut seed = None;
    let mut argi = 1;

    test_threads();
    test_crypto();
    test_math();

    if args.len() < 4 {
        print_usage(&args[0]);
        return;
    }

    if argi < args.len() && !args[argi].chars().all(|c| c.is_ascii_digit()) {
        dtype = &args[argi];
        argi += 1;
    }
    if args.len() - argi < 3 {
        eprintln!("Error: M N K are required.");
        print_usage(&args[0]);
        return;
    }
    let m = args[argi].parse().unwrap_or(0);
    let n = args[argi+1].parse().unwrap_or(0);
    let k = args[argi+2].parse().unwrap_or(0);
    argi += 3;
    if argi < args.len() {
        repeat = args[argi].parse().unwrap_or(1);
        argi += 1;
    }
    if argi < args.len() {
        let s = &args[argi];
        clean = s == "1" || s == "true" || s == "yes";
        argi += 1;
    }
    if argi < args.len() {
        seed = Some(args[argi].parse().unwrap_or(0));
        argi += 1;
    }
    if argi != args.len() {
        eprintln!("Error: too many arguments.");
        print_usage(&args[0]);
        return;
    }
    if m == 0 || n == 0 || k == 0 {
        eprintln!("Error: M N K must be positive integers.");
        return;
    }
    let a_count = m * n;
    let b_count = n * k;
    let c_count = m * k;
    let mut rng = SimpleRng::new(seed.unwrap_or_else(|| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0)
            ^ 0x6a09e667f3bcc909
    }));
    println!("==================================================================");
    println!("Testing naive matmul ...");
    println!("");
    let mut aggregated_value = 0.0f64;
    let mut times_matmul = vec![];
    let mut times_data_prep = vec![];
    let mut times_sum = vec![];
    let mut times_total = vec![];
    use std::f64::MAX;
    let mut min_matmul_time = MAX;
    let mut max_matmul_time = 0.0;
    let mut min_data_prep_time = MAX;
    let mut max_data_prep_time = 0.0;
    let mut min_sum_time = MAX;
    let mut max_sum_time = 0.0;
    let mut min_total_time = MAX;
    let mut max_total_time = 0.0;
    match dtype {
        "float32" | "f32" => {
            let mut a = vec![0f32; a_count];
            let mut b = vec![0f32; b_count];
            let mut c = vec![0f32; c_count];
            fill_random_f32(&mut a, &mut rng);
            fill_random_f32(&mut b, &mut rng);
            for _ in 0..repeat {
                let total_t0 = Instant::now();
                let mut data_prep_dt = Duration::ZERO;
                if clean {
                    let prep_t0 = Instant::now();
                    fill_random_f32(&mut a, &mut rng);
                    fill_random_f32(&mut b, &mut rng);
                    data_prep_dt = prep_t0.elapsed();
                }
                let t0 = Instant::now();
                matmul_f32(&a, &b, &mut c, m, n, k);
                let matmul_dt = t0.elapsed();
                let t0 = Instant::now();
                aggregated_value += sum_matrix_f32(&c);
                let sum_dt = t0.elapsed();
                let total_dt = total_t0.elapsed();
                times_data_prep.push(data_prep_dt);
                times_matmul.push(matmul_dt);
                times_sum.push(sum_dt);
                times_total.push(total_dt);
                if data_prep_dt.as_secs_f64() < min_data_prep_time { min_data_prep_time = data_prep_dt.as_secs_f64(); }
                if data_prep_dt.as_secs_f64() > max_data_prep_time { max_data_prep_time = data_prep_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() < min_matmul_time { min_matmul_time = matmul_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() > max_matmul_time { max_matmul_time = matmul_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() < min_sum_time { min_sum_time = sum_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() > max_sum_time { max_sum_time = sum_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() < min_total_time { min_total_time = total_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() > max_total_time { max_total_time = total_dt.as_secs_f64(); }
            }
        },
        "float64" | "f64" | "double" => {
            let mut a = vec![0f64; a_count];
            let mut b = vec![0f64; b_count];
            let mut c = vec![0f64; c_count];
            fill_random_f64(&mut a, &mut rng);
            fill_random_f64(&mut b, &mut rng);
            for _ in 0..repeat {
                let total_t0 = Instant::now();
                let mut data_prep_dt = Duration::ZERO;
                if clean {
                    let prep_t0 = Instant::now();
                    fill_random_f64(&mut a, &mut rng);
                    fill_random_f64(&mut b, &mut rng);
                    data_prep_dt = prep_t0.elapsed();
                }
                let t0 = Instant::now();
                matmul_f64(&a, &b, &mut c, m, n, k);
                let matmul_dt = t0.elapsed();
                let t0 = Instant::now();
                aggregated_value += sum_matrix_f64(&c);
                let sum_dt = t0.elapsed();
                let total_dt = total_t0.elapsed();
                times_data_prep.push(data_prep_dt);
                times_matmul.push(matmul_dt);
                times_sum.push(sum_dt);
                times_total.push(total_dt);
                if data_prep_dt.as_secs_f64() < min_data_prep_time { min_data_prep_time = data_prep_dt.as_secs_f64(); }
                if data_prep_dt.as_secs_f64() > max_data_prep_time { max_data_prep_time = data_prep_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() < min_matmul_time { min_matmul_time = matmul_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() > max_matmul_time { max_matmul_time = matmul_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() < min_sum_time { min_sum_time = sum_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() > max_sum_time { max_sum_time = sum_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() < min_total_time { min_total_time = total_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() > max_total_time { max_total_time = total_dt.as_secs_f64(); }
            }
        },
        "int64" | "i64" => {
            let mut a = vec![0i64; a_count];
            let mut b = vec![0i64; b_count];
            let mut c = vec![0i64; c_count];
            fill_random_i64(&mut a, &mut rng);
            fill_random_i64(&mut b, &mut rng);
            for _ in 0..repeat {
                let total_t0 = Instant::now();
                let mut data_prep_dt = Duration::ZERO;
                if clean {
                    let prep_t0 = Instant::now();
                    fill_random_i64(&mut a, &mut rng);
                    fill_random_i64(&mut b, &mut rng);
                    data_prep_dt = prep_t0.elapsed();
                }
                let t0 = Instant::now();
                matmul_i64(&a, &b, &mut c, m, n, k);
                let matmul_dt = t0.elapsed();
                let t0 = Instant::now();
                aggregated_value += sum_matrix_i64(&c);
                let sum_dt = t0.elapsed();
                let total_dt = total_t0.elapsed();
                times_data_prep.push(data_prep_dt);
                times_matmul.push(matmul_dt);
                times_sum.push(sum_dt);
                times_total.push(total_dt);
                if data_prep_dt.as_secs_f64() < min_data_prep_time { min_data_prep_time = data_prep_dt.as_secs_f64(); }
                if data_prep_dt.as_secs_f64() > max_data_prep_time { max_data_prep_time = data_prep_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() < min_matmul_time { min_matmul_time = matmul_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() > max_matmul_time { max_matmul_time = matmul_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() < min_sum_time { min_sum_time = sum_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() > max_sum_time { max_sum_time = sum_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() < min_total_time { min_total_time = total_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() > max_total_time { max_total_time = total_dt.as_secs_f64(); }
            }
        },
        "int32" | "i32" => {
            let mut a = vec![0i32; a_count];
            let mut b = vec![0i32; b_count];
            let mut c = vec![0i32; c_count];
            fill_random_i32(&mut a, &mut rng);
            fill_random_i32(&mut b, &mut rng);
            for _ in 0..repeat {
                let total_t0 = Instant::now();
                let mut data_prep_dt = Duration::ZERO;
                if clean {
                    let prep_t0 = Instant::now();
                    fill_random_i32(&mut a, &mut rng);
                    fill_random_i32(&mut b, &mut rng);
                    data_prep_dt = prep_t0.elapsed();
                }
                let t0 = Instant::now();
                matmul_i32(&a, &b, &mut c, m, n, k);
                let matmul_dt = t0.elapsed();
                let t0 = Instant::now();
                aggregated_value += sum_matrix_i32(&c);
                let sum_dt = t0.elapsed();
                let total_dt = total_t0.elapsed();
                times_data_prep.push(data_prep_dt);
                times_matmul.push(matmul_dt);
                times_sum.push(sum_dt);
                times_total.push(total_dt);
                if data_prep_dt.as_secs_f64() < min_data_prep_time { min_data_prep_time = data_prep_dt.as_secs_f64(); }
                if data_prep_dt.as_secs_f64() > max_data_prep_time { max_data_prep_time = data_prep_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() < min_matmul_time { min_matmul_time = matmul_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() > max_matmul_time { max_matmul_time = matmul_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() < min_sum_time { min_sum_time = sum_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() > max_sum_time { max_sum_time = sum_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() < min_total_time { min_total_time = total_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() > max_total_time { max_total_time = total_dt.as_secs_f64(); }
            }
        },
        "int16" | "i16" => {
            let mut a = vec![0i16; a_count];
            let mut b = vec![0i16; b_count];
            let mut c = vec![0i16; c_count];
            fill_random_i16(&mut a, &mut rng);
            fill_random_i16(&mut b, &mut rng);
            for _ in 0..repeat {
                let total_t0 = Instant::now();
                let mut data_prep_dt = Duration::ZERO;
                if clean {
                    let prep_t0 = Instant::now();
                    fill_random_i16(&mut a, &mut rng);
                    fill_random_i16(&mut b, &mut rng);
                    data_prep_dt = prep_t0.elapsed();
                }
                let t0 = Instant::now();
                matmul_i16(&a, &b, &mut c, m, n, k);
                let matmul_dt = t0.elapsed();
                let t0 = Instant::now();
                aggregated_value += sum_matrix_i16(&c);
                let sum_dt = t0.elapsed();
                let total_dt = total_t0.elapsed();
                times_data_prep.push(data_prep_dt);
                times_matmul.push(matmul_dt);
                times_sum.push(sum_dt);
                times_total.push(total_dt);
                if data_prep_dt.as_secs_f64() < min_data_prep_time { min_data_prep_time = data_prep_dt.as_secs_f64(); }
                if data_prep_dt.as_secs_f64() > max_data_prep_time { max_data_prep_time = data_prep_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() < min_matmul_time { min_matmul_time = matmul_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() > max_matmul_time { max_matmul_time = matmul_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() < min_sum_time { min_sum_time = sum_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() > max_sum_time { max_sum_time = sum_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() < min_total_time { min_total_time = total_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() > max_total_time { max_total_time = total_dt.as_secs_f64(); }
            }
        },
        _ => {
            let mut a = vec![0i8; a_count];
            let mut b = vec![0i8; b_count];
            let mut c = vec![0i8; c_count];
            fill_random_i8(&mut a, &mut rng);
            fill_random_i8(&mut b, &mut rng);
            for _ in 0..repeat {
                let total_t0 = Instant::now();
                let mut data_prep_dt = Duration::ZERO;
                if clean {
                    let prep_t0 = Instant::now();
                    fill_random_i8(&mut a, &mut rng);
                    fill_random_i8(&mut b, &mut rng);
                    data_prep_dt = prep_t0.elapsed();
                }
                let t0 = Instant::now();
                matmul_i8(&a, &b, &mut c, m, n, k);
                let matmul_dt = t0.elapsed();
                let t0 = Instant::now();
                aggregated_value += sum_matrix_i8(&c);
                let sum_dt = t0.elapsed();
                let total_dt = total_t0.elapsed();
                times_data_prep.push(data_prep_dt);
                times_matmul.push(matmul_dt);
                times_sum.push(sum_dt);
                times_total.push(total_dt);
                if data_prep_dt.as_secs_f64() < min_data_prep_time { min_data_prep_time = data_prep_dt.as_secs_f64(); }
                if data_prep_dt.as_secs_f64() > max_data_prep_time { max_data_prep_time = data_prep_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() < min_matmul_time { min_matmul_time = matmul_dt.as_secs_f64(); }
                if matmul_dt.as_secs_f64() > max_matmul_time { max_matmul_time = matmul_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() < min_sum_time { min_sum_time = sum_dt.as_secs_f64(); }
                if sum_dt.as_secs_f64() > max_sum_time { max_sum_time = sum_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() < min_total_time { min_total_time = total_dt.as_secs_f64(); }
                if total_dt.as_secs_f64() > max_total_time { max_total_time = total_dt.as_secs_f64(); }
            }
        }
    }
    println!("Input:");
    println!("  dtype  = {}", dtype);
    println!("  M N K  = {} {} {}", m, n, k);
    println!("  repeat = {}", repeat);
    println!("  clean  = {}", clean);
    println!("  seed   = {:?}", seed);
    println!("  aggregated_value = {:.12}", aggregated_value);
    println!("");
    println!("Timing (seconds):");
    println!("  matmul_time min = {:.9}, max = {:.9}", min_matmul_time, max_matmul_time);
    println!("  data_prep   min = {:.9}, max = {:.9}", min_data_prep_time, max_data_prep_time);
    println!("  sum         min = {:.9}, max = {:.9}", min_sum_time, max_sum_time);
    println!("  total       min = {:.9}, max = {:.9}", min_total_time, max_total_time);
}
