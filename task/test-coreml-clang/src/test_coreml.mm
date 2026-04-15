#import <Foundation/Foundation.h>
#import <CoreML/CoreML.h>
#include <iostream>

int main() {
    @autoreleasepool {
        MLModelConfiguration *cfg = [[MLModelConfiguration alloc] init];

        std::cout << "Core ML framework linked successfully\n";

        if (cfg) {
            std::cout << "MLModelConfiguration created successfully\n";
        } else {
            std::cout << "Failed to create MLModelConfiguration\n";
            return 1;
        }

        std::cout << "Done\n";
    }
    return 0;
}
