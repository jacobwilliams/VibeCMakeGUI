#include <stdio.h>

int main(void) {
#ifdef HELLO_GREETING
  printf("Hello, %s world!\n", HELLO_FLAVOR);
#endif
  return 0;
}
