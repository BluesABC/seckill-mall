#pragma once
#include <string_view>

namespace mall {
enum class OrderState { pending_payment, paid, closed };
enum class RequestState {
  reserved,
  queued,
  order_created,
  compensating,
  failed
};
constexpr bool can_transition(OrderState from, OrderState to) noexcept {
  return from == OrderState::pending_payment &&
         (to == OrderState::paid || to == OrderState::closed);
}
constexpr bool can_transition(RequestState from, RequestState to) noexcept {
  return (from == RequestState::reserved &&
          (to == RequestState::queued || to == RequestState::compensating)) ||
         (from == RequestState::queued && (to == RequestState::order_created ||
                                           to == RequestState::compensating)) ||
         (from == RequestState::compensating && to == RequestState::failed);
}
inline constexpr std::string_view contract_version = "1.0.0";
// Actual payment/close arbitration MUST use a database conditional update.
} // namespace mall
