#include <iostream>
#include <cstring>
#include <iomanip>
#include <openssl/opensslv.h>
#include <openssl/crypto.h>
#include <openssl/sha.h>

int main() {
    // 1. Print OpenSSL version
    std::cout << "OpenSSL version: "
              << OpenSSL_version(OPENSSL_VERSION) << std::endl;

    // 2. Compute SHA-256 of "hello world"
    const char* msg = "hello world";
    unsigned char hash[SHA256_DIGEST_LENGTH];

    SHA256(reinterpret_cast<const unsigned char*>(msg),
           strlen(msg), hash);

    std::cout << "SHA256(\"hello world\") = ";
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        std::cout << std::hex << std::setw(2)
                  << std::setfill('0') << (int)hash[i];
    }
    std::cout << std::endl;

    return 0;
}
