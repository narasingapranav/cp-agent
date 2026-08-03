class Solution:
    def maxPairStrength(self, nums: list[int]) -> int:
        def gcd(a,b):
            if b==0:
                return a
            return gcd(b,a%b)
        res=0
        n=len(nums)
        for i in range(n):
            for j in range(i+1,n):
                gc=gcd(nums[i],nums[j])
                res=max(res,nums[i]*nums[j]//(gc*gc))
        return res