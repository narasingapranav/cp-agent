class Solution:
    def uniqueXorTriplets(self, nums: List[int]) -> int:
        n=len(nums)
        temp=set()
        for i in range(n):
            for j in range(i,n):
                temp.add(nums[i]^nums[j])
        res=set()
        for i in nums:
            for j in temp:
                res.add(i^j)
        return len(res)