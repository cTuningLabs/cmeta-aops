/**
 * gemm.h: This file is part of the PolyBench/C 3.2 test suite.
 *
 *
 * Contact: Louis-Noel Pouchet <pouchet@cse.ohio-state.edu>
 * Web address: http://polybench.sourceforge.net
 */
#ifndef GEMM_H
# define GEMM_H

/* Default to STANDARD_DATASET. */
# if !defined(MINI_DATASET) && !defined(SMALL_DATASET) && !defined(LARGE_DATASET) && !defined(EXTRALARGE_DATASET)
#  define STANDARD_DATASET
# endif

/* Do not define anything if the user manually defines the size. */
# if !defined(NI) && !defined(NJ) && !defined(NK)
/* Define the possible dataset sizes. */
#  ifdef MINI_DATASET
#   define NI 32
#   define NJ 32
#   define NK 32
#  endif

#  ifdef SMALL_DATASET
#   define NI 128
#   define NJ 128
#   define NK 128
#  endif

#  ifdef STANDARD_DATASET /* Default if unspecified. */
#   define NI 1024
#   define NJ 1024
#   define NK 1024
#  endif

#  ifdef LARGE_DATASET
#   define NI 2000
#   define NJ 2000
#   define NK 2000
#  endif

#  ifdef EXTRALARGE_DATASET
#   define NI 4000
#   define NJ 4000
#   define NK 4000
#  endif
# endif /* !N */

# define _PB_NI POLYBENCH_LOOP_BOUND(NI,ni)
# define _PB_NJ POLYBENCH_LOOP_BOUND(NJ,nj)
# define _PB_NK POLYBENCH_LOOP_BOUND(NK,nk)

# ifndef DATA_TYPE
#  define DATA_TYPE double
# endif

/* Select the correct printf format string at compile time based on DATA_TYPE.
 *
 * The token-pasting trick works on all C preprocessors (C89+, MSVC, GCC,
 * Clang).  Two levels of indirection are required so that DATA_TYPE is fully
 * expanded (e.g. to "double") before ## concatenates it into the lookup name.
 *
 * Usage: -DDATA_TYPE=double  →  DATA_TYPE_double_FMT  →  "%0.2lf "
 */
# define DATA_TYPE_double_FMT "%0.2lf "
# define DATA_TYPE_float_FMT  "%0.2f "
# define DATA_TYPE_long_FMT   "%ld "
# define DATA_TYPE_int_FMT    "%d "

# define DATA_PRINTF_MODIFIER_PASTE(t) DATA_TYPE_ ## t ## _FMT
# define DATA_PRINTF_MODIFIER_EXPAND(t) DATA_PRINTF_MODIFIER_PASTE(t)
# define DATA_PRINTF_MODIFIER DATA_PRINTF_MODIFIER_EXPAND(DATA_TYPE)

#endif /* !GEMM */
