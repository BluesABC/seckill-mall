#include <iostream>
#include "mall/contracts.hpp"

int main() {
  using namespace mall;
  int failed = 0;
  const OrderState orders[] = {OrderState::pending_payment, OrderState::paid, OrderState::closed};
  for (auto from : orders) for (auto to : orders) {
    const bool expected = from == OrderState::pending_payment && to != from;
    if (can_transition(from, to) != expected) ++failed;
  }
  const RequestState requests[] = {RequestState::reserved, RequestState::queued,
    RequestState::order_created, RequestState::compensating, RequestState::failed};
  // Exhaustively verify terminal states cannot be reopened and failed is reachable
  // only after compensation, rather than treating a send timeout as failure.
  for (auto from : requests) for (auto to : requests) {
    if ((from == RequestState::failed || from == RequestState::order_created) &&
        can_transition(from, to)) ++failed;
    if (to == RequestState::failed && from != RequestState::compensating &&
        can_transition(from, to)) ++failed;
  }
  if (!can_transition(RequestState::reserved, RequestState::queued) ||
      !can_transition(RequestState::queued, RequestState::order_created) ||
      !can_transition(RequestState::compensating, RequestState::failed)) ++failed;
  std::cout << "state contract failures=" << failed << '\n';
  return failed == 0 ? 0 : 1;
}
