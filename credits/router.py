from fastapi import APIRouter, Depends
from core.dependencies import get_current_user
from credits.service import (
    get_user,
    reward_daily_login,
    reward_twitter_follow
)
from payments.paystack import initiate_payment

router = APIRouter(prefix="/credits", tags=["Credits"])


@router.get("/")
def get_balance(current_user=Depends(get_current_user)):
    user = get_user(current_user["id"])
    return {"credits": user["credits"]}


@router.post("/daily-login")
def daily_login(current_user=Depends(get_current_user)):
    user = get_user(current_user["id"])
    rewarded = reward_daily_login(user)
    return {"rewarded": rewarded}


@router.post("/twitter-follow")
def twitter_follow(current_user=Depends(get_current_user)):
    user = get_user(current_user["id"])
    reward_twitter_follow(user)
    return {"rewarded": True}


@router.post("/paystack/init")
def paystack_init(amount: int, current_user=Depends(get_current_user)):
    return initiate_payment(current_user["email"], amount)
