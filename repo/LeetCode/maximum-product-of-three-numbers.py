class Solution:
    def maximumProduct(self, nums: List[int]) -> int:
        nums.sort()
        s1=nums[0]*nums[1]*nums[-1]
        s2=nums[-1]*nums[-2]*nums[-3]
        return max(s1,s2)