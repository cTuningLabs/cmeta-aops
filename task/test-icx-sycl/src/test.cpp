#include <sycl/sycl.hpp>
#include <iostream>

int main() {
    try {
        // Pick default device (CPU/GPU)
        sycl::queue q;

        std::cout << "Running on: "
                  << q.get_device().get_info<sycl::info::device::name>()
                  << std::endl;

        const int N = 16;
        std::vector<int> data(N, 1);

        {
            sycl::buffer<int> buf(data.data(), sycl::range<1>(N));

            q.submit([&](sycl::handler& h) {
                auto acc = buf.get_access<sycl::access::mode::read_write>(h);

                h.parallel_for(N, [=](sycl::id<1> i) {
                    acc[i] *= 2;
                });
            });
        }

        std::cout << "Result: ";
        for (auto v : data) std::cout << v << " ";
        std::cout << std::endl;

    } catch (const sycl::exception& e) {
        std::cerr << "SYCL exception: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
